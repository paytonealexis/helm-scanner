 # Helm-Scanner Graph Viewer

This website allows you to search and view CVE and misconfiguration graphs for all [Artifact Hub](ArtifactHub.io) Helm charts scanned by Helm Scanner.

Helm Scanner scans both Helm chart misconfigurations as well as known image vulnerabilities and visualizes the results with a graph. You can use this repository of graphs to see how every Helm chart on [Artifact Hub](ArtifactHub.io) *including the ones in your own infrastructure* stacks up. You can [search](/helm-scanner/search/) by known CVE, chart name, and Checkov policy name. 

Read more about our research methodology [on our blog](https://bridgecrew.io/blog/helm-scanner-graphing-misconfigurations-and-cves-blast-radius) and check out the [Helm Scanner code](https://github.com/bridgecrewio/helm-scanner) for yourself.


We created this tool to help teams visualize the impact, or "blast radius," of infrastructure as code (IaC) misconfigurations when vulnerabilities (CVEs) are also present in the consumed container images.
The graphs contain interconnected nodes of the following data:

* Lime green nodes: Any Kubernetes resource type with one or more Checkov violations.
* Teal nodes: Any infrastructure misconfigurations found in the Helm charts. These appear on the graph as [Checkov](https://checkov.io) policy violations.
* Orange nodes: Any images defined within the Kubernetes resource.
* Yellow nodes: Any CVEs with a CVSS score above 5 found within the scanned images.

![Example Graph](/helm-scanner/img/example.png)

With this information, our aim is to help visualize a potential attack by allowing you to see connections between insecure infrastructure configurations and the CVE attack surfaces they may expose.
We welcome feedback, ideas, and suggestions via our [GitHub issues page](https://github.com/bridgecrewio/helm-scanner/issues) where you will also find [the source for Helm Scanner](https://github.com/bridgecrewio/helm-scanner) and graph builder itself.

To use the site, pick a Helm chart from the list below or use the [Search](/helm-scanner/search/). Then select `VIEW BLASTRADIUS GRAPH` to view the graph as a Bokeh interactive graph.

---
