import datetime
import os
import errno
import sys
from collections import defaultdict
import subprocess
import wget
import traceback
import tarfile
import glob
import re
import logging as helmscanner_logging

from helmScanner.collect import artifactHubCrawler
from helmScanner.output import result_writer
from helmScanner.output import s3_uploader
from helmScanner.multithreader import multithreadit
from helmScanner.image_scanner import imageScanner
from helmScanner.scannerTimeStamp import currentRunTimestamp
from helmScanner.scannerTimeStamp import currentRunResultsPath



# Local setup of checkov
from checkov.logging_init import init as logging_init
from checkov.helm.registry import registry
from checkov.helm.runner import Runner as helm_runner

class Scanner:

    #Toremove
    globalDepsUsage = {}
    globalDepsList = defaultdict(list)
    emptylist = []

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

        repoName = repoResult['name']
        repoDetailsDict = repoResult

        chartNameFromResultDataExpression = '(.*)\.(RELEASE-NAME-)?(.*)(\.default)?'
        chartNameFromResultDataExpressionGroup = 3

        repoChartPathName = f"{repo['name']}/{chartPackage['name']}"
        ## DEBUG: Disable specific repo for scanning
        #if orgRepoFilename == "reponame":
        #    continue
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
            helmout = subprocess.Popen(["helm", 'template', f"{downloadPath}/{chartPackage['name']}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = helmout.communicate()
            imageList = []
            for line in out.decode('utf-8').split('\n'):
                if 'image:' in line:
                    line = line.replace('"', '')
                    line = line.replace(' ', '')
                    img=line.split(':')
                    imagename = img[1]
                    # if there's no tag it means "latest"
                    if len(img) < 3:
                        tag = "latest"
                    else:
                        tag = img[2]
                    imageList.append(f"{imagename}:{tag}")
            # get rid of the duplicates to save time
            imageList = list(dict.fromkeys(imageList))
            #helmscanner_logging.info(f"Scanner: Found images: {imageList} in chart {downloadPath}/{chartPackage['name']}")

            #imageScanner._scan_images(repoChartPathName, imageList) 
            #helmscanner_logging.info(f"Scanner: Done Scanning Images {imageList} for chart: {downloadPath}/{chartPackage['name']}")
            
            # Assign results_scan outside of try objects.
            results_scan = object
            try:
                helmscanner_logging.info(f"Scanner: {repo['name']}/{chartPackage['name']} | Running Checkov")
                runner = helm_runner()
                results_scan = runner.run(root_folder=downloadPath, external_checks_dir=None, files=None)
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

                        helmdeps_lst.append(dep_item)
                    
            except:
                pass

   # helmscanner_logging.debug(f"Global deps usage: {globalDepsUsage}")
    #helmscanner_logging.debug(f"Global deps list {globalDepsList}")

    #result_writer.print_csv(summary_lst, result_lst, helmdeps_lst, empty_resources, currentRunResultsPath, repo['name'], orgRepoFilename, globalDepsList, globalDepsUsage)
    #Upload and rename per org, rather than waiting till the end of the run.
    #uploadResultsPartial()

