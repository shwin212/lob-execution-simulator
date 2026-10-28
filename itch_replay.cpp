// ITCH normalized-event replay engine, C++17. No third-party dependencies.
// Usage: build/itch_replay sample/demo.csv
// Benchmark the *same* normalized CSV (parsing cost included for both engines).
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <list>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

struct Order {
    char side;
    int64_t price;
    uint64_t shares;
    std::list<uint64_t>::iterator pos;
};

class Book {
    std::map<int64_t, std::list<uint64_t>> bids, asks;
    std::unordered_map<uint64_t, Order> orders;
    uint64_t events = 0, executed_shares = 0;

    std::map<int64_t, std::list<uint64_t>>& levels(char side) {
        if (side == 'B') return bids;
        if (side == 'S') return asks;
        throw std::runtime_error("invalid side");
    }

    void add(uint64_t id, char side, uint64_t shares, int64_t price) {
        if (orders.count(id) || !shares || price <= 0) throw std::runtime_error("duplicate/invalid add");
        auto& q = levels(side)[price];
        q.push_back(id);
        orders.emplace(id, Order{side, price, shares, std::prev(q.end())});
    }

    void del(uint64_t id) {
        auto it = orders.find(id);
        if (it == orders.end()) throw std::runtime_error("unknown order ID");
        auto& side_levels = levels(it->second.side);
        auto level = side_levels.find(it->second.price);
        level->second.erase(it->second.pos);
        if (level->second.empty()) side_levels.erase(level);
        orders.erase(it);
    }

    void reduce(uint64_t id, uint64_t shares) {
        auto it = orders.find(id);
        if (it == orders.end()) throw std::runtime_error("unknown order ID");
        if (!shares || shares > it->second.shares) throw std::runtime_error("invalid reduction");
        it->second.shares -= shares;
        if (it->second.shares == 0) del(id);
    }

    uint64_t level_qty(const std::list<uint64_t>& q) const {
        uint64_t total = 0;
        for (auto id : q) total += orders.at(id).shares;
        return total;
    }

public:
    void apply(const std::vector<std::string>& v) {
        if (v.size() != 9) throw std::runtime_error("invalid CSV field count");
        const std::string kind = v.at(1);
        uint64_t id = std::stoull(v.at(2));
        uint64_t shares = std::stoull(v.at(4));
        int64_t price = std::stoll(v.at(5));
        uint64_t new_id = std::stoull(v.at(6));
        if (kind == "A" || kind == "F") {
            if (v.at(3).size() != 1) throw std::runtime_error("missing side");
            add(id, v.at(3)[0], shares, price);
        } else if (kind == "E" || kind == "C" || kind == "X") {
            reduce(id, shares);
            if (kind != "X") executed_shares += shares;
        } else if (kind == "D") {
            del(id);
        } else if (kind == "U") {
            auto it = orders.find(id);
            if (it == orders.end()) throw std::runtime_error("missing replace ID");
            char side = it->second.side;
            del(id);
            add(new_id, side, shares, price);
        } else {
            throw std::runtime_error("unknown message kind");
        }
        ++events;
    }

    void print_json() const {
        std::cout << "{\"bids\":[";
        bool first = true;
        unsigned depth = 0;
        for (auto it = bids.rbegin(); it != bids.rend() && depth < 5; ++it, ++depth) {
            if (!first) std::cout << ',';
            first = false;
            std::cout << "{\"price_ticks\":" << it->first
                      << ",\"shares\":" << level_qty(it->second) << '}';
        }
        std::cout << "],\"asks\":[";
        first = true;
        depth = 0;
        for (auto it = asks.begin(); it != asks.end() && depth < 5; ++it, ++depth) {
            if (!first) std::cout << ',';
            first = false;
            std::cout << "{\"price_ticks\":" << it->first
                      << ",\"shares\":" << level_qty(it->second) << '}';
        }
        std::cout << "],\"live_orders\":" << orders.size()
                  << ",\"events\":" << events
                  << ",\"executed_shares\":" << executed_shares << "}\n";
    }
};

std::vector<std::string> split_csv(const std::string& line) {
    // Normalized schema contains only integers, enumerated ASCII, and a bare symbol.
    // Quoted CSV fields are not supported by this intentionally minimal parser.
    std::vector<std::string> out;
    std::stringstream ss(line);
    std::string cell;
    while (std::getline(ss, cell, ',')) out.push_back(cell);
    if (!line.empty() && line.back() == ',') out.emplace_back();
    return out;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "Usage: itch_replay events.csv\n";
        return 2;
    }
    try {
        std::ifstream file(argv[1]);
        if (!file) throw std::runtime_error("could not open input");
        std::string line;
        if (!std::getline(file, line)) throw std::runtime_error("missing CSV header");
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line != "ts_ns,kind,order_id,side,shares,price_ticks,new_order_id,symbol,trade_price_ticks") {
            throw std::runtime_error("CSV header mismatch");
        }
        Book book;
        while (std::getline(file, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;
            book.apply(split_csv(line));
        }
        book.print_json();
    } catch (const std::exception& e) {
        std::cerr << "Replay failed: " << e.what() << '\n';
        return 1;
    }
}
