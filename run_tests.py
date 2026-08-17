import unittest

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # تحميل جميع اختبارات الـ Unit والـ Resilience معاً
    suite.addTests(loader.discover("tests/unit"))
    suite.addTests(loader.discover("tests/resilience"))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)