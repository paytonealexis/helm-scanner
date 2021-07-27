#!/usr/bin/python3

#from pyvis.network import Network
import networkx as nx

class GraphBuilder():
    def __init__(self):
        # New NetworkX graph
        self.G = nx.Graph()

    def _visualise_graph(networkxGraph):
        #net = Network(notebook=True)
        #net.from_nx(networkxGraph)
        #net.show("helm-results.html")
        print("TODO.")

    def addNode(self, something): 
        # G.add_node(1, time='5pm')
        # G.add_nodes_from([3], time='2pm')
        # G.nodes[1]
        # {'time': '5pm'}
        # G.nodes[1]['room'] = 714
        # G.nodes.data()
        # NodeDataView({1: {'time': '5pm', 'room': 714}, 3: {'time': '2pm'}})
        print("TODO.")

graphBuilder = GraphBuilder()
