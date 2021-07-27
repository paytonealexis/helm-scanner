import pickle

def numberOfCharts(dict):
    totalPackages = 0
    for repo in dict:
        totalPackages += dict[repo]['repoTotalPackages']
    return totalPackages

crawlDict = {}
with open('artifactHubCrawler.crawl.pickle', 'rb') as f:
    crawlDict = pickle.load(f)
    print("Loaded pickle file")


print(f"Number of charts in Results: {numberOfCharts(crawlDict)}")

smallSampleCrawlDict = {}
i = 1
chopsize = 4
while i < chopsize:
    smallSampleCrawlDict[i] = crawlDict[i]
    i = i + 1

newChartCount = numberOfCharts(smallSampleCrawlDict)
print(f"Number of Charts in new subset: {newChartCount}")

with open(f'artifactHubCrawler-smallsample-{newChartCount}repos.crawl.pickle', 'wb') as f:
    pickle.dump(smallSampleCrawlDict, f, pickle.HIGHEST_PROTOCOL)
    print(f"New Picke file created with first {chopsize} repos, containing {newChartCount} charts.")





