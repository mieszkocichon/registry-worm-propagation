import unittest
import pandas as pd
from graph_builder import build_bipartite_graph
import json
import os

class TestGraphBuilder(unittest.TestCase):
    def setUp(self):
        self.test_file = 'test_metadata.jsonl'
        data = [
            {'package': 'pkgA', 'maintainers': ['m1', 'm2', 'bot-service-account']},
            {'package': 'pkgB', 'maintainers': ['m2', 'm3']},
            {'package': 'pkgC', 'maintainers': ['m1', 'renovate[bot]']},
            {'package': 'pkgD', 'maintainers': ['m4', 'm5']},
        ]
        with open(self.test_file, 'w', encoding='utf-8') as f:
            for d in data:
                f.write(json.dumps(d) + '\n')
                
    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
            
    def test_bipartite_graph_construction(self):
        # 1. Test without package filter
        npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(self.test_file)
        
        self.assertEqual(len(pkg_list), 4)
        # bot-service-account (prefix bot-) and renovate[bot] ([bot] suffix) must be
        # excluded by the build-time is_bot filter — this is the canonical behaviour
        # after migrating the bot filter from fetch-time to graph-build-time.
        self.assertEqual(set(m_list), {'m1', 'm2', 'm3', 'm4', 'm5'})
        self.assertNotIn('bot-service-account', set(m_list))
        self.assertNotIn('renovate[bot]', set(m_list))
        
        # Test shape: 4 packages x 5 human maintainers (2 bots stripped)
        self.assertEqual(B_csr.shape, (4, 5))
        
        # Check specific edges
        pkgA_idx = pkg_to_idx['pkgA']
        m1_idx = m_to_idx['m1']
        m2_idx = m_to_idx['m2']
        
        self.assertEqual(B_csr[pkgA_idx, m1_idx], 1)
        self.assertEqual(B_csr[pkgA_idx, m2_idx], 1)
        
        # Check that factorize preserved order parity
        for i, m in enumerate(m_list):
            self.assertEqual(m_to_idx[m], i)
            
    def test_bipartite_graph_filter(self):
        # 2. Test with allowed_packages
        npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(self.test_file, allowed_packages={'pkgB', 'pkgD'})
        
        self.assertEqual(len(pkg_list), 2)
        self.assertEqual(set(pkg_list), {'pkgB', 'pkgD'})
        self.assertEqual(set(m_list), {'m2', 'm3', 'm4', 'm5'})
        
        self.assertEqual(B_csr.shape, (2, 4))
        
if __name__ == '__main__':
    unittest.main()
