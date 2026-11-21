// Single-source shortest paths (Dijkstra) on a weighted undirected graph.
//
// This is the target of the AAE quick-start example: it is correct but slow on
// purpose. Do not optimize it by hand; let an AAE session do it.
//
// Input format (text): first line "n m", then m lines "u v w" with 0-based node
// IDs and positive integer weights; every line is one undirected edge.
// Output: for each of the sources 0, n/4, n/2, 3n/4 one line
// "source reachable sum_of_distances max_distance".

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

typedef std::map<int, std::map<int, long> > Graph;

Graph read_graph(const std::string& path, int& n) {
    std::ifstream in(path.c_str());
    if (!in) {
        std::cerr << "cannot open " << path << std::endl;
        std::exit(1);
    }
    long m;
    in >> n >> m;
    Graph graph;
    for (int u = 0; u < n; ++u) graph[u];
    for (long i = 0; i < m; ++i) {
        int u, v;
        long w;
        in >> u >> v >> w;
        // keep the lighter edge if there are parallel edges
        if (graph[u].count(v) == 0 || graph[u][v] > w) graph[u][v] = w;
        if (graph[v].count(u) == 0 || graph[v][u] > w) graph[v][u] = w;
    }
    return graph;
}

std::map<int, long> dijkstra(const Graph& graph, int source) {
    std::map<int, long> dist;
    std::set<std::pair<long, int> > queue;
    dist[source] = 0;
    queue.insert(std::make_pair(0L, source));
    while (!queue.empty()) {
        std::pair<long, int> top = *queue.begin();
        queue.erase(queue.begin());
        int u = top.second;
        std::map<int, long> neighbors = graph.at(u);  // copy of the adjacency
        for (std::map<int, long>::iterator it = neighbors.begin(); it != neighbors.end(); ++it) {
            int v = it->first;
            long candidate = dist[u] + it->second;
            if (dist.count(v) == 0 || candidate < dist[v]) {
                if (dist.count(v)) queue.erase(std::make_pair(dist[v], v));
                dist[v] = candidate;
                queue.insert(std::make_pair(candidate, v));
            }
        }
    }
    return dist;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: sssp graph_file" << std::endl;
        return 1;
    }
    int n;
    Graph graph = read_graph(argv[1], n);
    std::vector<int> sources;
    sources.push_back(0);
    sources.push_back(n / 4);
    sources.push_back(n / 2);
    sources.push_back(3 * (n / 4));
    for (size_t i = 0; i < sources.size(); ++i) {
        std::map<int, long> dist = dijkstra(graph, sources[i]);
        long sum = 0, max = 0;
        for (std::map<int, long>::iterator it = dist.begin(); it != dist.end(); ++it) {
            sum += it->second;
            if (it->second > max) max = it->second;
        }
        std::cout << sources[i] << " " << dist.size() << " " << sum << " " << max << std::endl;
    }
    return 0;
}
