
from bs4 import BeautifulSoup
import csv
import sys
import json
   
def line_prepender(filename, line):
    with open(filename, 'r+') as f:
        content = f.read()
        f.seek(0, 0)
        f.write(line.rstrip('\r\n') + '\n' + content)

#file = "/Users/matt/bcd/bcd-47-helm-dockerimage-scanning/verummeum/content/blog/2021/adwerx-github-actions-runner.html"
file = sys.argv[1]
graphname = file.replace(".html", "", 1)


f = open(file, "r")
   
soup = BeautifulSoup(f.read(), 'html5lib')
   
ckvChecks=[]  
cves=[]

#print(soup.prettify())
   
table = soup.find('script', attrs = {'type':'application/json'}) 

#print(table)
graphBlobJson = json.loads(table.contents[0])

for i in graphBlobJson:
    for j in graphBlobJson[i]['roots']['references']:
       if j['type'] == "ColumnDataSource":
           if "index" in j["attributes"]["data"] :
            for k in j["attributes"]["data"]["index"]:
                    if "CVE" in k:
                        cves.append(k)
                    if "CKV" in k:
                        ckvChecks.append(k)
tags = "["
if len(cves) > 0: 
    for i in cves:
        tags = tags + f'"{i}",'
if len(ckvChecks) > 0:
    for i in ckvChecks:
        tags = tags + f'"{i}",'
tags = tags + "]"
tags = tags.replace(",]", "]", 1)

line_prepender(file, "+++")
line_prepender(file, f'categories = "HELM"')
line_prepender(file, f"tags = {tags}")
line_prepender(file, f'title = "{graphname}" ')
line_prepender(file, "+++")


#print(ckvChecks)
#print(cves)
   
# for row in table.findAll('div',
#                          attrs = {'class':'col-6 col-lg-3 text-center margin-30px-bottom sm-margin-30px-top'}):
#     quote = {}
#     quote['theme'] = row.h5.text
#     quote['url'] = row.a['href']
#     quote['img'] = row.img['src']
#     quote['lines'] = row.img['alt'].split(" #")[0]
#     quote['author'] = row.img['alt'].split(" #")[1]
#     quotes.append(quote)
   
# filename = 'inspirational_quotes.csv'
# with open(filename, 'w', newline='') as f:
#     w = csv.DictWriter(f,['theme','url','img','lines','author'])
#     w.writeheader()
#     for quote in quotes:
#         w.writerow(quote)