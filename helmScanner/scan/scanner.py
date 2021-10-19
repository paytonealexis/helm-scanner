import datetime
import os
import errno
import sys
from collections import defaultdict
import subprocess
from bokeh.models.glyphs import VArea
from checkov.runner_filter import RunnerFilter
from networkx.algorithms.cuts import normalized_cut_size
import wget
import traceback
import tarfile
import glob
import re
import logging as helmscanner_logging
import networkx as nx
import matplotlib.pyplot as plt
from bokeh import plotting
from bokeh.models import ColumnDataSource, LabelSet, Circle, HoverTool, TapTool, BoxSelectTool
from bokeh.transform import factor_cmap
import yaml
import io

from helmScanner.collect import artifactHubCrawler
from helmScanner.output import result_writer
from helmScanner.output import s3_uploader
from helmScanner.multithreader import multithreadit
from helmScanner.image_scanner import imageScanner
from helmScanner.scannerTimeStamp import currentRunTimestamp
from helmScanner.scannerTimeStamp import currentRunResultsPath
from helmScanner.multithreader import getJobQueue


# Local setup of checkov
from checkov.logging_init import init as logging_init
from checkov.helm.registry import registry
from checkov.helm.runner import Runner as helm_runner

class Scanner:

    globalDepsUsage = {}
    globalDepsList = defaultdict(list)
    emptylist = []
    chartGraph = None

    def check_category(self, check_id):
        if (registry.get_check_by_id(check_id)) is not None:
            return registry.get_check_by_id(check_id).categories[0]

    def extract(self, tar_url, extract_path='.'):
        helmscanner_logging.debug(tar_url)
        tar = tarfile.open(tar_url, 'r')
        for item in tar:
            tar.extract(item, extract_path)
            if item.name.find(".tgz") != -1 or item.name.find(".tar") != -1:
                self.extract(item.name, "./" + item.name[:item.name.rfind('/')])


    def parse_helm_dependency_output(self, o):
        output = o.decode('utf-8')
        chart_dependencies={}
        if "WARNING" in output:
            #Helm output showing no deps, example: 'WARNING: no dependencies at helm-charts/charts/prometheus-kafka-exporter/charts\n'
            pass
        else: 
            lines = output.split('\n')
            for line in lines:
                if line != "":
                    if not "NAME" in line:
                        chart_name, chart_version, chart_repo, chart_status = line.split("\t")
                        chart_dependencies.update({chart_name.rstrip():{'chart_name': chart_name.rstrip(), 'chart_version': chart_version.rstrip(), 'chart_repo': chart_repo.rstrip(), 'chart_status': chart_status.rstrip()}})
        return chart_dependencies

    def gen_dict_extract(self, key, var, foundImages=[]):
        if hasattr(var,'items'):
            for k, v in var.items():
                if k == key:
                    yield v
                if isinstance(v, dict):
                        #helmscanner_logging.debug(f"Found a {type(v)}. Contents: {v}")
                        for result in self.gen_dict_extract(key, v):
                            yield result

                elif isinstance(v, list):
                        #helmscanner_logging.debug(f"Found a {type(v)}. Contents: {v}")
                        for d in v:
                            for result in self.gen_dict_extract(key, d):
                                yield result

    def scan_single_chart(self, chartVersionResponse, repoResult):

        repo = repoResult
        chartPackage = chartVersionResponse
        summary_lst = []
        result_lst = []
        helmdeps_lst = []
        empty_resources = {}
        orgRepoFilename = f"{repoResult['name']}"
        extract_failures = []
        download_failures = []
        parse_deps_failures = []

        repoName = repoResult

        chartNameFromResultDataExpression = '(.*)\.(RELEASE-NAME-)?(.*)(\.default)?'
        chartNameFromResultDataExpressionGroup = 3

        repoChartPathName = f"{repo['name']}/{chartPackage['name']}"

        if True:
            helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']}| Download Source ")
            # Setup local dir and download
            repoChartPathName = f"{repo['name']}/{chartPackage['name']}"
            downloadPath = f'{currentRunResultsPath}/{repoChartPathName}'

            if not os.path.exists(downloadPath):
                    os.makedirs(downloadPath)
            try:
                wget.download(chartPackage['content_url'], downloadPath)
                for filename in glob.glob(f"{downloadPath}/**.tgz", recursive=False):
                    try: 
                        self.extract(filename, downloadPath)
                        helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']}| Extract Source ")
                        os.remove(filename)
                    except:
                        helmscanner_logging.warning(f"Scanner: Failed to extract {repo['name']}/{chartPackage['name']}")
                        extract_failures.append([f"{repo['name']}/{chartPackage['name']}"])
                
            except:
                helmscanner_logging.error(f"Scanner: Failed to download {repo['name']}/{chartPackage['name']}")
                download_failures.append([f"{repo['name']}/{chartPackage['name']}"])
                return 
        

            helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']} | Processing Chart Deps")
            proc = subprocess.Popen(["helm", 'dependency', 'list' , f"{downloadPath}/{chartPackage['name']}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            o, e = proc.communicate()
            if e:
                if "Warning: Dependencies" in str(e, 'utf-8'):
                    helmscanner_logging.warning(f"Scanner: V1 API chart without Chart.yaml dependancies. Skipping dependancy list creation for {chartPackage['name']} at dir: {downloadPath}/{chartPackage['name']}. Error details: {str(e, 'utf-8')}")
                else: 
                    helmscanner_logging.warning(f"Scanner: Error processing helm dependancies for {chartPackage['name']} at source dir: {downloadPath}/{chartPackage['name']}. Error details: {str(e, 'utf-8')}")
            chart_deps = self.parse_helm_dependency_output(o)
            helmscanner_logging.debug(chart_deps)

            #Chart Graph
            graphName = f"{repo['name']}/{chartPackage['name']}"
            self.chartGraph = nx.Graph(name=graphName)
            self.chartGraph.add_node(graphName, name=graphName, description=graphName)
            self.chartGraph.nodes[graphName]['nodeType'] = "root"
            
            self.chartGraph.add_node("deps", name="Chart Deps")
            self.chartGraph.nodes["deps"]['nodeType'] = "root"

            helmout = subprocess.Popen(["helm", 'template', f"{downloadPath}/{chartPackage['name']}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = helmout.communicate()

            # Assign results_scan outside of try objects.
            results_scan = object
            try:
                helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']} | Running Checkov")
                runner = helm_runner()
                results_scan = runner.run(root_folder=downloadPath, external_checks_dir=None, files=None, runner_filter=RunnerFilter(skip_checks="CKV_K8S_21"))
                res = results_scan.get_dict()
                helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']} | Processing Checkov Results")
                for passed_check in res["results"]["passed_checks"]:
                    chartNameFromResultData = re.search(chartNameFromResultDataExpression, passed_check["resource"]).group(chartNameFromResultDataExpressionGroup)
                    ## NEW. Default items if no key exists for non-critical components
                    check = [
                        currentRunTimestamp,
                        repoChartPathName,
                        repo['name'],
                        chartPackage['name'],
                        chartPackage['version'],
                        chartPackage['ts'],
                        chartPackage.get('signed','no data'),
                        chartPackage.get('security_report_created_at','no data'),
                        chartNameFromResultData,   
                        chartPackage.get('is_operator','no data'),
                        str(self.check_category(passed_check["check_id"])).lstrip("CheckCategories."),
                        passed_check["check_id"],
                        passed_check["check_name"],
                        passed_check["check_result"]["result"],
                        passed_check["file_path"],
                        passed_check["check_class"],
                        passed_check["resource"].split(".")[0],
                        repo['repository_id'],
                        repo['digest'],
                        repo['last_tracking_ts'],
                        repo['verified_publisher'],
                        repo['official'],
                        repo['scanner_disabled']
                        ]

                    result_lst.append(check)
                for failed_check in res["results"]["failed_checks"]:
                    chartNameFromResultData = re.search(chartNameFromResultDataExpression, failed_check["resource"]).group(chartNameFromResultDataExpressionGroup)
                    check = [
                        currentRunTimestamp,
                        repoChartPathName,
                        repo['name'],
                        chartPackage['name'],
                        chartPackage['version'],
                        chartPackage['ts'],
                        chartPackage.get('signed','no data'),
                        chartPackage.get('security_report_created_at','no data'),
                        chartNameFromResultData,   
                        chartPackage.get('is_operator','no data'),
                        str(self.check_category(failed_check["check_id"])).lstrip("CheckCategories."),
                        failed_check["check_id"],
                        failed_check["check_name"],
                        failed_check["check_result"]["result"],
                        failed_check["file_path"],
                        failed_check["check_class"],
                        failed_check["resource"].split(".")[0],
                        repo['repository_id'],
                        repo['digest'],
                        repo['last_tracking_ts'],
                        repo['verified_publisher'],
                        repo['official'],
                        repo['scanner_disabled']
                        ]

                    # Failed checks add to graph by check ID grouping
                    if not "tests" in failed_check["file_path"]:
                        if f'{failed_check["check_id"]}[0]' not in self.chartGraph:
                            self.chartGraph.add_node(failed_check["check_id"], name=failed_check["check_id"], description=failed_check["check_name"])
                            self.chartGraph.nodes[failed_check["check_id"]]['nodeType'] = "checkov"
                            self.chartGraph.add_edge(failed_check["check_id"], graphName)
                        # Normalise resource name (we already know the graph name)
                        regex = r"([A-Za-z0-9]*)\..*-?\ ?(.*)"              
                        normalizedResourceRegex = re.findall(regex, failed_check['resource'])
                        if normalizedResourceRegex[0][1] == '': 
                            normalizedResourceName = f"{normalizedResourceRegex[0][0]}.default"
                        else:
                            normalizedResourceName = f"{normalizedResourceRegex[0][0]}.{normalizedResourceRegex[0][1]}"
                        self.chartGraph.add_node(normalizedResourceName, name=normalizedResourceName, description=failed_check["resource"], filePath=failed_check["file_path"])
                        self.chartGraph.nodes[normalizedResourceName]['nodeType'] = "helmResource"
                        self.chartGraph.add_edge(normalizedResourceName, failed_check["check_id"])
                    #check.extend(self.add_meta(scan_time))
                    result_lst.append(check)
                if results_scan.is_empty():
                    check = [
                        currentRunTimestamp,
                        repoChartPathName,
                        repo['name'],
                        chartPackage['name'],
                        chartPackage['version'],
                        chartPackage['ts'],
                        chartPackage.get('signed','no data'),
                        chartPackage.get('security_report_created_at','no data'),
                        "empty scan",   
                        chartPackage.get('is_operator','no data'),
                        "empty scan",
                        "empty scan",
                        "empty scan",
                        "empty scan",
                        "empty scan",
                        "empty scan",
                        "empty scan",
                        repo['repository_id'],
                        repo['digest'],
                        repo['last_tracking_ts'],
                        repo['verified_publisher'],
                        repo['official'],
                        repo['scanner_disabled']
                        ]
                    #check.extend(self.add_meta(scan_time))
                    result_lst.append(check)
                    #empty_resources = self.module_resources()
            except Exception:
                helmscanner_logging.error('unexpected error in scan')
                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb = traceback.format_exception(exc_type, exc_value, exc_traceback)
                check = [
                        currentRunTimestamp,
                        repoChartPathName,
                        repo['name'],
                        chartPackage['name'],
                        chartPackage['version'],
                        chartPackage['ts'],
                        chartPackage.get('signed','no data'),
                        chartPackage.get('security_report_created_at','no data'),
                        "error in scan",   
                        chartPackage.get('is_operator','no data'),
                        "error in scan",
                        "error in scan",
                        "error in scan",
                        "error in scan",
                        "error in scan",
                        "error in scan",
                        "error in scan",
                        repo['repository_id'],
                        "error in scan",
                        "error in scan",
                        repo['verified_publisher'],
                        repo['official'],
                        repo['scanner_disabled']
                        ]

                result_lst.append(check)

            # Summary Results
            try:
                helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']} | Processing Checkov Summaries")
                res = results_scan.get_dict()
                summary_lst_item = [
                    currentRunTimestamp,
                    repoChartPathName,
                    repo['name'],
                    chartPackage['name'],
                    chartPackage['version'],
                    chartPackage['ts'],
                    chartPackage.get('signed', 'No Data'),
                    chartPackage.get('security_report_created_at', 'No Data'),
                    chartPackage['name'],   
                    chartPackage.get('is_operator', 'No Data'),
                    "success",
                    res["summary"]["passed"],
                    res["summary"]["failed"],
                    res["summary"]["parsing_errors"]
                ]
            except:
                summary_lst_item = [
                    currentRunTimestamp,
                    repoChartPathName,
                    repo['name'],
                    chartPackage['name'],
                    chartPackage['version'],
                    chartPackage['ts'],
                    chartPackage.get('signed', 'No Data'),
                    chartPackage.get('security_report_created_at', 'No Data'),
                    chartPackage['name'],   
                    chartPackage.get('is_operator', 'No Data'),
                    "failed",
                    0,
                    0,
                    0
                ]

            summary_lst.append(summary_lst_item)

            #Scan images after Checkov results added to graph. (dependancies on edges to attach too)

            imageData = []
            # We need the resource for each found image so we can link it to the graph on the right resource node for CVE's
            # Read YAML file
            for doc in yaml.safe_load_all(out.decode('utf-8')):
                helmscanner_logging.info(f"Scanner: HELM Image Parsing. Current Object: {graphName}/{doc['kind']}/{doc['metadata']['name']}")                
                parseImageGenerator = self.gen_dict_extract('image', doc) 
                for i in parseImageGenerator:
                        img=i.split(':')
                        imagename = img[0]
                        # if there's no tag it means "latest"
                        if len(img) <= 1:
                            tag = "latest"
                        else:
                            tag = img[1]
                        # Normalise resource name
                        regex = r".*\.(.*)"              
                        normalizedResourceRegex = re.findall(regex, doc['metadata']['name'])
                        if normalizedResourceRegex == []: 
                            normalizedResourceName = f"{doc['kind']}.default"
                        else:
                            normalizedResourceName = f"{doc['kind']}.{normalizedResourceRegex[0][0]}"
                        imageData.append({'imagename':imagename, 'tag': tag, 'resourceKind': doc['kind'], 'resourcename': doc['metadata']['name'], 'normalizedResourceName':normalizedResourceName})
                
        
            helmscanner_logging.debug(f"Scanner: Found images: {imageData} in chart {downloadPath}/{chartPackage['name']}")
            imageScanner._scan_images(repoChartPathName, imageData, self) 
            helmscanner_logging.info(f"Scanner: Done Scanning Images {imageData} for chart: {downloadPath}/{chartPackage['name']}")

            # Helm Dependancies
            try:
                res = results_scan.get_dict()
                helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']} | Processing Helm Dependancies")
                #{'common': {'chart_name': 'common', 'chart_version': '0.0.5', 'chart_repo': 'https://charts.adfinis.com', 'chart_status': 'unpacked'}}
                if chart_deps:
                    for key in chart_deps:
                        helmscanner_logging.debug(f" HELMDEP FOUND! {chart_deps[key]}")
                        current_dep = chart_deps[key]
                        
                        dep_item = [
                            currentRunTimestamp,
                            repoChartPathName, #Current chart combined repo/path
                            repo['name'],  #Current chart reponame
                            chartPackage['name'], #Current chart chartname
                            chartPackage['version'], #Current chart version
                            list(current_dep.values())[0], #dep dict chart_name
                            list(current_dep.values())[1], #dep dict chart_version
                            list(current_dep.values())[2], #dep dict chart_repo
                            list(current_dep.values())[3]  #dep dict chart_status
                        ]

                        self.chartGraph.add_node(chartPackage['name'], name=chartPackage['name'], description=chartPackage['name'])
                        self.chartGraph.nodes[chartPackage['name']]['nodeType'] = "chart"
                        self.chartGraph.add_edge(chartPackage['name'], "deps", color="red")

                        helmdeps_lst.append(dep_item)
                    
            except:
                pass

        plot = plotting.figure(title=f"{repo['name']}-{chartPackage['name']}", plot_width=1024, plot_height=768)#, x_range=(-1.1,1.1), y_range=(-1.1,1.1))
        plot.add_tools(HoverTool(tooltips=[("Name", "@name"), 
                                        ("NodeType", "@nodeType"), 
                                        ("Description", "@description")]), 
                    TapTool(), 
                    BoxSelectTool())


        bokehGraph = plotting.from_networkx(self.chartGraph, nx.spring_layout, scale=1, center=(0,0))

        plot.renderers.append(bokehGraph)

        positions = bokehGraph.layout_provider.graph_layout
        x, y = zip(*positions.values())
        node_labels = nx.get_node_attributes(self.chartGraph, 'name')


        bokehGraph.node_renderer.data_source.data['name'] = list(self.chartGraph.nodes())
        bokehGraph.node_renderer.data_source.data['nodeType'] = [i[1] for i in self.chartGraph.nodes(data='nodeType')]
        bokehGraph.node_renderer.data_source.data['description'] = [i[1] for i in self.chartGraph.nodes(data='description')]

        bokehGraph.node_renderer.data_source.data['x']=x
        bokehGraph.node_renderer.data_source.data['y']=y
        bokehGraph.node_renderer.glyph = Circle(size=20, fill_color=factor_cmap('nodeType', 'Spectral8', ['root', 'checkov', 'chart', 'helmResource', 'CVE', 'image']))
        labels = LabelSet(x='x', y='y', text='name', source=bokehGraph.node_renderer.data_source, background_fill_color='white')





        plot.renderers.append(labels)
        plotting.output_file(f"{currentRunResultsPath}/graphs-html/{repo['name']}-{chartPackage['name']}.html")
        plotting.show(plot)
        #helmscanner_logging.debug(f"Global deps usage: {globalDepsUsage}")
        #helmscanner_logging.debug(f"Global deps list {globalDepsList}")

        result_writer.print_csv(summary_lst, result_lst, helmdeps_lst, empty_resources, currentRunResultsPath, repo['name'], f"{repo['name']}-{chartPackage['name']}") #,globalDepsList, globalDepsUsage)
    #Upload and rename per org, rather than waiting till the end of the run.
    #uploadResultsPartial()

