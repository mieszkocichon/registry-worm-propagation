import unittest
import os
import shutil
from pathlib import Path
from data_utils import hash_file_endpoints, clean_old_caches

class TestDataUtils(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path('test_data_dir')
        self.test_dir.mkdir(exist_ok=True)
        (self.test_dir / 'data').mkdir(exist_ok=True)
        
        self.file1 = self.test_dir / 'file1.txt'
        self.file2 = self.test_dir / 'file2.txt'
        
        # Write files with identical size, identical first/last chunks, but different middle chunk
        # First/last chunks are 1200 bytes of "Hello World!", middle is "a" vs "b"
        with open(self.file1, 'w') as f:
            f.write("Hello World!" * 100 + "a" * 2000 + "Hello World!" * 100)
            
        with open(self.file2, 'w') as f:
            f.write("Hello World!" * 100 + "b" * 2000 + "Hello World!" * 100)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_hash_file_endpoints_full_collision_safety(self):
        # Verify sizes are identical
        self.assertEqual(os.stat(self.file1).st_size, os.stat(self.file2).st_size)
        
        # Verify first and last blocks are identical
        with open(self.file1, 'rb') as f1, open(self.file2, 'rb') as f2:
            self.assertEqual(f1.read(100), f2.read(100))
            f1.seek(-100, 2)
            f2.seek(-100, 2)
            self.assertEqual(f1.read(100), f2.read(100))
            
        # The new full-file hashing must produce different hashes to prevent collision.
        hash1 = hash_file_endpoints(self.file1)
        hash2 = hash_file_endpoints(self.file2)
        self.assertNotEqual(hash1, hash2, "Collision error: files with identical sizes and endpoints must have different hashes")

    def test_clean_old_caches(self):
        data_dir = self.test_dir / 'data'
        cache_d = data_dir / 'D_csr_cache_active.pkl'
        cache_b = data_dir / 'B_csr_cache_active.pkl'
        cache_old = data_dir / 'D_csr_cache_old.pkl'
        
        cache_d.touch()
        cache_b.touch()
        cache_old.touch()
        
        clean_old_caches(data_dir, current_d_hash='active', current_b_hash='active')
        
        self.assertTrue(cache_d.exists())
        self.assertTrue(cache_b.exists())
        self.assertFalse(cache_old.exists())

if __name__ == '__main__':
    unittest.main()
