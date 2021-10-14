
"""
ArtifactHub.io HELM Crawler v0.4
================================
Matt Johnson <matt@bridgecrew.io> 
Steve Giguere <eurogig@gmail.com>

:env ARTIFACTHUB_TOKEN: API token from artifacthub.io
:env ARTIFACTHUB_TOKEN_SECRET: API secret from artifacthub.io
"""

import logging as helmscanner_logging
import logging.handlers
import os
import pickle
from urllib.parse import urlparse

# Retries and exponential backoffs
import requests
from requests.exceptions import HTTPError
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from helmScanner.utils.timeoutHttpAdaptor import TimeoutHTTPAdapter

from helmScanner.multithreader import singleJobQueueIt
from helmScanner.scan.scanner import Scanner
from helmScanner.utils.getArgs import args



class ArtifactHubCrawler:

    def __init__(self):

        logfile = "./artifacthub-crawler.log"

        # Logging Setup
        logger = helmscanner_logging.getLogger()
        logger.setLevel(helmscanner_logging.INFO)
        filehandler = helmscanner_logging.handlers.RotatingFileHandler(logfile, maxBytes=1024000, backupCount=1)
        filehandler.setLevel(helmscanner_logging.INFO)
        ch = helmscanner_logging.StreamHandler()
        ch.setLevel(helmscanner_logging.INFO)
        logger.addHandler(filehandler)
        logger.addHandler(ch)
        self.logger = logger

        # Requests setup
        self.http = requests.Session()
        retries = Retry(total=3, backoff_factor=10, status_forcelist=[429, 500, 502, 503, 504])
        self.http.mount("https://", TimeoutHTTPAdapter(max_retries=retries))


    def crawl(self):
        """
        crawl uses the HELM search functioanlity of artifacthub.io to find all helm *repositories* which may contain multiple charts.
        It then queries each repository to find charts, and uses the direct download link for each chart to get the latest .tgz.
        The chart is extracted and location recorded.
        Testing/Debugging: We also then dump the dictionary to a pickle file: artifactHubCrawler.crawl.pickle, which was historically useful for inspecting the data post-run.
        
        :return crawlDict: A dictionary of crawled and discovered HELM charts, their repo details, and the local filesystem tmpdir location of the extracted chart.
        :return totalReposFromAPI: Integer stat of total repo's discovered 
        :return totalPackages: Integer stat of total Chart's within all discovered repo's 

        """
        crawlDict = {}
        totalPackages = 0
        reposPerRequest = 60 #API Limit
        start_record = int(args.start_record)
        max_records = args.max_record
        helmscanner_logging.info("Crawler: Artifacthub Helm crawler started.")
        try:
            currentRepo = 0
            headers = {'X-API-KEY-ID': args.artifacthub_token , 'X-API-KEY-SECRET': args.artifacthub_secret}
            helmscanner_logging.info("Receiving latest ArtifactHub repo results.")
            response = self.http.get(f"https://artifacthub.io/api/v1/repositories/search?offset={start_record}&limit={reposPerRequest}&kind=0", headers=headers)
            response.raise_for_status()
            totalReposFromAPI = int(response.headers["pagination-total-count"])
            reposToProcess = totalReposFromAPI if max_records > totalReposFromAPI else max_records
            self.logger.debug(f"Crawler: Max repos set to: {reposToProcess}. API reports {totalReposFromAPI} repos.")
            jsonResponse = response.json()
            totalReposReceived = len(jsonResponse)
            reposToProcess = reposToProcess - totalReposReceived       
            offset = start_record + totalReposReceived
            while ((reposToProcess - start_record) > 0):
                # Get the rest of the repos
                response = self.http.get(f"https://artifacthub.io/api/v1/repositories/search?offset={offset}&limit={reposPerRequest}&kind=0", headers=headers)
                response.raise_for_status()
                jsonResponse += response.json()
                reposToProcess = reposToProcess - len(response.json())
                offset += reposPerRequest
                totalReposReceived += len(response.json())
            self.logger.info(f"Crawler: Downloaded {totalReposReceived} Repo's. Artifacthub.io repos avalable: {totalReposFromAPI}. Helm-Scanner limit set to: {max_records} ")
            
            for repoResult in jsonResponse:
                thisRepoDict = {}
                currentRepo += 1
                try:
                    repoOrgName = repoResult['organization_name']
                except:
                    repoOrgName = repoResult['user_alias']
                try:
                    # Packages within a repo
                    self.logger.info(f"Crawler: {currentRepo}/{totalReposReceived} | Processing Repo {repoResult['name']} by {repoOrgName}")
                    packagesQueryURI = f"https://artifacthub.io/api/v1/packages/search?limit=60&facets=false&kind=0&repo={repoResult['name']}"
                    response = self.http.get(packagesQueryURI, headers=headers)
                    chartPackages = response.json()
                    chartPackagesInRepo = len(chartPackages['packages'])
                    self.logger.info(f"Crawler: {currentRepo}/{totalReposReceived} | found {chartPackagesInRepo} packages.")
                    thisRepoDict = {"repoName": repoResult['name'], "repoOrgName": repoOrgName, "repoCrawlResultsID": currentRepo, "repoTotalPackages": chartPackagesInRepo, "repoRaw": repoResult, "repoPackages": [] }
                    currentChartPackage = 0
                    for chartPackage in chartPackages['packages']:
                        scanner = Scanner()
                        currentChartPackage += 1
                        totalPackages +=1
                        try:
                            # Downloads and package version details for each package.
                            response = self.http.get(f"https://artifacthub.io/api/v1/packages/helm/{repoResult['name']}/{chartPackage['name']}", headers=headers)
                            chartVersionResponse = response.json()
                            self.logger.debug(f"Crawler: R: {currentRepo}/{totalReposReceived} | P: {currentChartPackage}/{chartPackagesInRepo} | Chart {chartPackage['name']} latest version: {chartVersionResponse['version']} URL: {chartVersionResponse['content_url']}")
                            thisRepoDict['repoPackages'].append(chartVersionResponse)

                            # Kick off multi-threaded scan of chart.
                            # TODO: Fix broken multithreading
                            #singleJobQueueIt(scanner.scan_single_chart,(chartVersionResponse,repoResult))
                            scanner.scan_single_chart(chartVersionResponse, repoResult)
                            
                        except HTTPError as http_err:
                           helmscanner_logging.warning(f'Crawler: HTTP error occurred: {http_err}')
                        except Exception as err:
                            helmscanner_logging.warning(f'Crawler: Other error occurred: {err}')
                except HTTPError as http_err:
                    helmscanner_logging.warning(f'Crawler: HTTP error occurred: {http_err}')
                except Exception as err:
                    helmscanner_logging.warning(f'Crawler: Other error occurred: {err}')
                #Save this repo's packages into our main crawler dict.
                crawlDict[currentRepo] = thisRepoDict
        except HTTPError as http_err:
            helmscanner_logging.warning(f'Crawler: HTTP error occurred: {http_err}')
        except Exception as err:
            helmscanner_logging.warning(f'Crawler: Other error occurred: {err}')
        with open('artifactHubCrawler.crawl.pickle', 'wb') as f:
            pickle.dump(crawlDict, f, pickle.HIGHEST_PROTOCOL)
        return crawlDict, totalReposReceived, totalPackages 
