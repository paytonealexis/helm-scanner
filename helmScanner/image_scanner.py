#!/usr/bin/python3

from sys import argv

import csv
import docker 
import os
import stat
import platform
import requests
from datetime import datetime, timedelta
import subprocess  # nosec
import json
import logging as helmscanner_logging
from slugify import slugify
from helmScanner.multithreader import multithreadit
from helmScanner.scannerTimeStamp import currentRunTimestamp
from helmScanner.scannerTimeStamp import currentRunResultsPath
from helmScanner.utils.getArgs import args
import re

# Get magic from checkov to build the headers
from checkov.common.util.data_structures_utils import merge_dicts
from checkov.common.util.http_utils import get_auth_header, get_default_get_headers, get_default_post_headers



class ImageScanner():
    def __init__(self):
        global args
        #super(ImageScanner, self).__init__()
        #args = getArgs.getArgs()
        self.TWISTCLI_FILE_NAME = 'twistcli'
        self.DOCKER_IMAGE_SCAN_RESULT_FILE_NAME = 'docker-image-scan-results.json'
        self.BC_API_URL = "https://www.bridgecrew.cloud/api/v1"
        self.BC_API_KEY = args.bridgecrew_api_key
        self.BC_SOURCE = "helm-scanner"


        self.cmds = []
        self.cli = docker.from_env()
        docker_image_scanning_base_url = f"{self.BC_API_URL}/vulnerabilities/docker-images"
        self.docker_image_scanning_proxy_address=f"{docker_image_scanning_base_url}/twistcli/proxy"
        self.download_twistcli(self.TWISTCLI_FILE_NAME,docker_image_scanning_base_url)
        pruned = self.cli.images.prune()
        helmscanner_logging.info(f"ImageScanner: Pruned images: {pruned}")

    def _scan_image(self, helmRepo, imageData, scannerObject): 
        #imageData in the form of Dict, example:
            # imagename: busybox
            # tag: latest
            # resourceKind: pod
            # resourceName: 'RELEASE-NAME-acos-prometheus-exporter-helm-chart-test-connection'
            # 
        docker_image_id = f"{imageData['imagename']}:{imageData['tag']}"


        docker_cli = docker.from_env()
        try:            img = docker_cli.images.get(docker_image_id)
        except:
            helmscanner_logging.info(f"ImageScanner: {docker_image_id} Not local, pulling.")
            try:
                helmscanner_logging.info(f"ImageScanner: Pulling {docker_image_id}")
                img = docker_cli.images.pull(imageData['imagename'],imageData['tag'])
            except:
                helmscanner_logging.info(f"ImageScanner: Can't pull image {docker_image_id}")
                return
        # Create Dockerfile.  Only required for platform reporting
        hist = img.history()
        cmds = self._parse_history(hist)
        cmds.reverse()
        self._save_dockerfile(cmds, img)
        DOCKER_IMAGE_SCAN_RESULT_FILE_NAME = f".{img.id}.json"
        command_args = f"./{self.TWISTCLI_FILE_NAME} images scan --address {self.docker_image_scanning_proxy_address} --token {self.BC_API_KEY} --details --output-file {DOCKER_IMAGE_SCAN_RESULT_FILE_NAME} {docker_image_id}".split()
        helmscanner_logging.info(f"ImageScanner: Running scan for {docker_image_id}")
        try:
            subprocess.run(command_args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # nosec
        except Exception as e:
            helmscanner_logging.error(f"ImageScanner: Error running twistcli scan. Exception is {e}")
        helmscanner_logging.info(f'ImageScanner: TwistCLI ran successfully on image {docker_image_id}')
        # if twistcli worked our json file should be there
        if os.path.isfile(DOCKER_IMAGE_SCAN_RESULT_FILE_NAME):
            with open(DOCKER_IMAGE_SCAN_RESULT_FILE_NAME) as docker_image_scan_result_file:
                self.parse_results(helmRepo, imageData, img.id, json.load(docker_image_scan_result_file), scannerObject) 
            os.remove(DOCKER_IMAGE_SCAN_RESULT_FILE_NAME)
        else:
            helmscanner_logging.warning(f'ImageScanner: no TwistCLI results file found for {docker_image_id}. Images and CVEs will be missing from the data.')
        try:
            docker_cli.images.remove(docker_image_id)
        except:
            pass

    def _scan_images(self, helmRepo, imageData, scannerObject): 

        multithreadit(self._scan_image, helmRepo, imageData, scannerObject)
        return
        
    def _save_dockerfile(self,cmds, img):
        if not os.path.exists(f"{currentRunResultsPath}/dockerfiles"):
            os.makedirs(f"{currentRunResultsPath}/dockerfiles")
        file = open(f"{currentRunResultsPath}/dockerfiles/{img.id}.Dockerfile","w")
        for i in cmds:
            file.write(i)
        file.close()

    def _parse_history(self, hist, rec=False):
        first_tag = False
        actual_tag = False
        cmds = []
        for i in hist:
            if i['Tags']:
                actual_tag = i['Tags'][0]
                if first_tag and not rec:
                    break
                first_tag = True
            step = i['CreatedBy']
            if "#(nop)" in step:
                to_add = step.split("#(nop) ")[1]
            else:
                to_add = ("RUN {}".format(step))
            to_add = to_add.replace("&&", "\\\n    &&")
            cmds.append(to_add.strip(' '))
        if not rec:
            cmds.append("IMAGE {}".format(actual_tag))
        return cmds

    def download_twistcli(self, cli_file_name, docker_image_scanning_base_url):
        if os.path.exists(cli_file_name):
            return
        os_type = platform.system().lower()
        headers = merge_dicts(
            get_default_get_headers(self.BC_SOURCE, "HELM_SCANNER"),
            get_auth_header(self.BC_API_KEY)
        )
        response = requests.request('GET', f"{docker_image_scanning_base_url}/twistcli/download?os={os_type}", headers=headers)
        open(cli_file_name, 'wb').write(response.content)
        st = os.stat(cli_file_name)
        os.chmod(cli_file_name, st.st_mode | stat.S_IEXEC)
        helmscanner_logging.info(f'ImageScanner: TwistCLI downloaded and has execute permission')

    def parse_results(self, helmRepo, imageData, image_id, twistcli_scan_result, scannerObject):
        headerRow = ['Scan Timestamp','Helm Repo','Image Name','Image Tag','Image SHA','Total', 'Critical', 'High', 'Medium','Low']
        filebase = slugify(f"{helmRepo}-{image_id[7:]}")
        filenameVulns = f"{currentRunResultsPath}/containers/{filebase}.csv"
        filenameSummary = f"{currentRunResultsPath}/container_summaries/{filebase}_summary.csv"
        imageName = imageData['imagename']
        imageTag = imageData['tag']
        # Create Summary
        try:
            with open(filenameSummary, 'w') as f: 
                write = csv.writer(f) 
                write.writerow(headerRow) 
                row = [
                    currentRunTimestamp,
                    helmRepo,
                    imageName,
                    imageTag,
                    image_id,
                    twistcli_scan_result['results'][0]['vulnerabilityDistribution']['total'],
                    twistcli_scan_result['results'][0]['vulnerabilityDistribution']['critical'],
                    twistcli_scan_result['results'][0]['vulnerabilityDistribution']['high'],
                    twistcli_scan_result['results'][0]['vulnerabilityDistribution']['medium'],
                    twistcli_scan_result['results'][0]['vulnerabilityDistribution']['low'] ]
                write.writerow(row) 
        except Exception as e: 
            helmscanner_logging.info(f'ImageScanner: Error opening CSV occured. Error was: {e}') 
        # Create Vulns Doc (if required)  
        if twistcli_scan_result['results'][0]['vulnerabilityDistribution']['total'] > 0:

            for x in twistcli_scan_result['results'][0]['vulnerabilities']:
                try:
                    link = x['link']
                except:
                    link = ''

                # Normalize names to attach to checkov parts of graph.
                normalizedResourceName = imageData['normalizedResourceName']
                normalizedImageName = f"{imageData['imagename']}:{imageData['tag']}"

                # Add Image name/detail graph objects first to attach CVE's to
                if normalizedImageName not in scannerObject.chartGraph:
                            scannerObject.chartGraph.add_node(normalizedImageName, name=normalizedImageName)
                            scannerObject.chartGraph.nodes[normalizedImageName]['nodeType'] = "image"
                            scannerObject.chartGraph.nodes[normalizedImageName]['imageVersion'] = imageData['tag']
                            scannerObject.chartGraph.add_edge(normalizedImageName, normalizedResourceName)

                if 'cvss' in x:
                     if x['cvss'] > 5:
                         scannerObject.chartGraph.add_node(x['id'], name=x['id'], description=x.get('description'))
                         scannerObject.chartGraph.nodes[x['id']]['nodeType'] = "CVE"
                         scannerObject.chartGraph.nodes[x['id']]['cvssScore'] = x['cvss']
                         scannerObject.chartGraph.nodes[x['id']]['parentNodeResource'] = imageData['resourceKind']
                         scannerObject.chartGraph.add_edge(x['id'], normalizedImageName )
                        #'RELEASE-NAME-acos-prometheus-exporter-helm-chart'
            headerRow = ['Scan Timestamp','Helm Repo','Image Name','Image Tag','Image SHA','CVE ID', 'Status', 'Severity', 'Package Name','Package Version','Link','CVSS','Vector','Description','Risk Factors','Publish Date','Is Remote Execution','Is Recent Vulnerability','CVE Has Fix']           
            with open(filenameVulns, 'w') as f: 
                write = csv.writer(f) 
                write.writerow(headerRow) 
                for x in twistcli_scan_result['results'][0]['vulnerabilities']:
                    try:
                        link = x['link']
                    except:
                        link = ''

                    riskFactorRemoteExecution = 0
                    riskFactorHasFix = 0
                    riskFactorRecentVuln = 0
                    if 'riskFactors' in x:
                        if "remote execution" in x.get('riskFactors'):
                            riskFactorRemoteExecution = 1
                        if "Recent vulnerability" in x.get('riskFactors'):
                            riskFactorRecentVuln = 1
                        if "has fix" in x.get('riskFactors'):
                            riskFactorHasFix = 1

                    row = [
                        currentRunTimestamp,
                        helmRepo,
                        imageName,
                        imageTag,
                        image_id,
                        x['id'],
                        x.get('status', 'open'),
                        x['severity'],
                        x['packageName'],
                        x['packageVersion'],
                        link,
                        x.get('cvss'),
                        x.get('vector'),
                        x.get('description'),
                        x.get('riskFactors'),
                        (datetime.now() - timedelta(days=x.get('publishedDays', 0))).isoformat(),
                        riskFactorRemoteExecution,
                        riskFactorRecentVuln,
                        riskFactorHasFix ]
                    write.writerow(row) 



imageScanner = ImageScanner()
