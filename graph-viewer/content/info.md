 # Helm-Scanner Graph Viewer

This website allows you to search and view CVE and Misconfiguration graphs for all [ArtifactHub.io](ArtifactHub.io) Helm charts scanned by Helm Scanner.

Helm Scanner scan's both Helm chart misconfigurations as well as known image vulnerabilities and visualize the results with a graph. You can use this repository of graphs to see how every Helm chart on [ArtifactHub.io](ArtifactHub.io) *including the ones in your own infrastructure* stacks up. You can [search](/helm-scanner/search/) by known CVE, chart name, and Checkov check name. 

Read more about our research methodology [on our blog](https://bridgecrew.io/blog/helm-scanner-graphing-misconfigurations-and-cves-blast-radius) and check out the [Helm Scanner code](https://github.com/bridgecrewio/helm-scanner) for yourself.


We created this tool to help teams' visualise the impact, or "blast radius" of infrastructure-as-code misconfigurations when vulnerabilities (CVE's) are also present in the consumed container images.
The graphs contain interconnected nodes of the following data:

* Any infrastructure miscofigurations found in the templated-out HELM charts. These appear on the graph as [Checkov.io](https://checkov.io) Policy violations.
* Any Kubernetes resource type with one or more Checkov violations.
* Any Images defined within the Kubernetes resource.
* Any CVE's with a CVSS score above 5 found within the scanned images.

![Example Graph](/helm-scanner/img/example.png)

With this information, our aim is to help visualize a potential attack, allowing the user to see connections between insecure infrastructure configurations and the CVE attack surfaces they may expose.
We welcome feedback, ideas and suggestions via our [github issues page](https://github.com/bridgecrewio/helm-scanner/issues) where you will also find [the source for the scanner](https://github.com/bridgecrewio/helm-scanner) and graph builder itself.

To use the site, pick a HELM chart from the list below or use the [Search](/helm-scanner/search/). Then click `VIEW BLASTRADIUS GRAPH` to view the graph as a Bokeh interactive graph.

---