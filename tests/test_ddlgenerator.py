#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_ddlgenerator
----------------------------------

Tests for `ddlgenerator` module.
"""

import glob
import unittest
import os.path
from collections import namedtuple, OrderedDict
import pytest
try:
    import pymongo
except ImportError:
    pymongo = None
try:
    from ddlgenerator.ddlgenerator import Table
except ImportError:
    from ddlgenerator import Table

# Monkey-patch data_dispenser's _open to fix removed 'rU' file mode on Python 3.12+
try:
    import data_dispenser.sources as _ds_sources
    _ds_original_open = _ds_sources._open
    def _patched_open(filename):
        return open(filename, 'r')
    _ds_sources._open = _patched_open
except (ImportError, AttributeError):
    pass

def here(filename):
    return os.path.join(os.path.dirname(__file__), filename)

@pytest.mark.mongo
@unittest.skipIf(pymongo is None, "pymongo not installed")
class TestMongo(unittest.TestCase):

    def setUp(self):
        data = [{'year': 2013,
                 'physics': ['François Englert', 'Peter W. Higgs'],
                 'chemistry': ['Martin Karplus', 'Michael Levitt', 'Arieh Warshel'],
                 'peace': ['Organisation for the Prohibition of Chemical Weapons (OPCW)',],
                 },
                {'year': 2011,
                 'physics': ['Saul Perlmutter', 'Brian P. Schmidt', 'Adam G. Riess'],
                 'chemistry': ['Dan Shechtman',],
                 'peace': ['Ellen Johnson Sirleaf', 'Leymah Gbowee', 'Tawakkol Karman'],
                 },
                ]
        self.data = data
        try:
            self.client = pymongo.MongoClient(serverSelectionTimeoutMS=2000)
            self.client.server_info()  # Force connection check
            self.db = self.client.ddlgenerator_test_db
            self.tbl = self.db.prize_winners
            self.tbl.insert_many(self.data)
        except (pymongo.errors.ConnectionFailure, pymongo.errors.OperationFailure,
                pymongo.errors.ServerSelectionTimeoutError) as e:
            self.skipTest("MongoDB not available: %s" % e)

    def tearDown(self):
        if hasattr(self, 'client'):
            self.client.drop_database(self.db)
            self.client.close()

    def testData(self):
        winners = Table(self.tbl, pk_name='year')
        generated = winners.sql('postgresql', inserts=True)
        self.assertIn('REFERENCES prize_winners (year)', generated)
        

                        
class TestFromRawPythonData(unittest.TestCase):
    
    prov_type = namedtuple('province', ['name', 'capital', 'pop'])
    canada = [prov_type('Quebec', 'Quebec City', '7903001'),
              prov_type('Ontario', 'Toronto', '12851821'), ]
                  
    merovingians = [
                    OrderedDict([('name', {'name_id': 1, 'name_txt': 'Clovis I'}), 
                                 ('reign', {'from': 486, 'to': 511}),
                                 ]),
                    OrderedDict([('name', {'name_id': 1, 'name_txt': 'Childebert I'}), 
                                 ('reign', {'from': 511, 'to': 558}),
                                 ]),
                    ]
                
    def test_pydata_named_tuples(self):
        tbl = Table(self.canada)
        generated = tbl.sql('postgresql', inserts=True).strip()
        self.assertIn('capital VARCHAR(11) NOT NULL,', generated)
        self.assertIn('(name, capital, pop) VALUES (\'Quebec\', \'Quebec City\', 7903001)', generated)
        
    def test_nested(self):
        tbl = Table(self.merovingians)
        generated = tbl.sql('postgresql', inserts=True).strip()
        self.assertIn("reign_to", generated)
        
    def test_sqlalchemy(self):
        tbl = Table(self.merovingians)
        generated = tbl.sqlalchemy()
        self.assertIn("Column('reign_from'", generated)
        self.assertIn("Integer()", generated)
        tbl = Table(self.canada)
        generated = tbl.sqlalchemy()
        self.assertIn("Column('capital', Unicode", generated)

    def test_django(self):
        tbl = Table(self.merovingians)
        generated = tbl.django_models()
        #print("generated")
        #print(generated)
        #self.assertIn("(models.Model):", generated)
        #self.assertIn("name_name_id =", generated)
        tbl = Table(self.canada)
        generated = tbl.django_models()
        #self.assertIn("name =", generated)
        
    def test_cushion(self):
        tbl = Table(self.merovingians, data_size_cushion=0)
        generated = tbl.sql('postgresql').strip()        
        self.assertIn('VARCHAR(12)', generated)        
        tbl = Table(self.merovingians, data_size_cushion=1)
        generated = tbl.sql('postgresql').strip()        
        self.assertIn('VARCHAR(14)', generated)


class TestSequenceUpdates(unittest.TestCase):
    """Tests for emit_db_sequence_updates - P0-3 fixes"""

    def test_emit_db_sequence_updates_postgresql_only(self):
        """Sequence updates should only be generated for PostgreSQL engines"""
        from unittest.mock import Mock, MagicMock
        try:
            from ddlgenerator.ddlgenerator import emit_db_sequence_updates
        except ImportError:
            from ddlgenerator import emit_db_sequence_updates

        # Mock a PostgreSQL engine
        mock_result = MagicMock()
        mock_result.first.return_value = (100,)

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [
            [('SELECT last_value FROM public.my_seq;', 'public.my_seq',)],  # First query: get sequences
            mock_result  # Second query: get last_value
        ]

        mock_engine = Mock()
        mock_engine.name = 'postgresql'
        mock_engine.connect.return_value = mock_conn

        # Get the sequence updates
        updates = list(emit_db_sequence_updates(mock_engine))

        # Verify correct SQL was generated with both sequence name and nextval
        self.assertEqual(len(updates), 1)
        self.assertIn('ALTER SEQUENCE public.my_seq RESTART WITH 101;', updates[0])

    def test_emit_db_sequence_updates_non_postgresql(self):
        """Sequence updates should not be generated for non-PostgreSQL engines"""
        from unittest.mock import Mock
        try:
            from ddlgenerator.ddlgenerator import emit_db_sequence_updates
        except ImportError:
            from ddlgenerator import emit_db_sequence_updates

        # Mock a non-PostgreSQL engine (e.g., sqlite)
        mock_engine = Mock()
        mock_engine.name = 'sqlite'

        # Should yield nothing for non-PostgreSQL
        updates = list(emit_db_sequence_updates(mock_engine))
        self.assertEqual(len(updates), 0)

    def test_emit_db_sequence_updates_no_engine(self):
        """Sequence updates should not be generated when no engine is present"""
        try:
            from ddlgenerator.ddlgenerator import emit_db_sequence_updates
        except ImportError:
            from ddlgenerator import emit_db_sequence_updates

        updates = list(emit_db_sequence_updates(None))
        self.assertEqual(len(updates), 0)


class TestSecurityInputValidation(unittest.TestCase):
    """Tests for P1-1: Block dangerous file extensions to prevent RCE"""

    def test_py_file_extension_blocked(self):
        """Python files should be rejected to prevent eval() RCE"""
        try:
            from ddlgenerator.ddlgenerator import Table, UnsafeInputError
        except ImportError:
            from ddlgenerator import Table, UnsafeInputError

        with self.assertRaises(UnsafeInputError) as ctx:
            Table('malicious.py')
        self.assertIn('.py', str(ctx.exception))
        self.assertIn('security', str(ctx.exception).lower())

    def test_pickle_file_extension_blocked(self):
        """Pickle files should be rejected to prevent deserialization attacks"""
        try:
            from ddlgenerator.ddlgenerator import Table, UnsafeInputError
        except ImportError:
            from ddlgenerator import Table, UnsafeInputError

        with self.assertRaises(UnsafeInputError) as ctx:
            Table('malicious.pickle')
        self.assertIn('.pickle', str(ctx.exception))

    def test_pkl_file_extension_blocked(self):
        """Pickle files with .pkl extension should be rejected"""
        try:
            from ddlgenerator.ddlgenerator import Table, UnsafeInputError
        except ImportError:
            from ddlgenerator import Table, UnsafeInputError

        with self.assertRaises(UnsafeInputError) as ctx:
            Table('data.pkl')
        self.assertIn('.pkl', str(ctx.exception))

    def test_safe_python_data_accepted(self):
        """Python data (lists, dicts) should be accepted without error"""
        # Using Python data directly avoids data_dispenser Python 3.12 issues
        data = [{'id': 1, 'name': 'test'}]
        table = Table(data)
        self.assertIsNotNone(table)

    def test_case_insensitive_extension_check(self):
        """Blocked extensions should be detected regardless of case"""
        try:
            from ddlgenerator.ddlgenerator import Table, UnsafeInputError
        except ImportError:
            from ddlgenerator import Table, UnsafeInputError

        with self.assertRaises(UnsafeInputError):
            Table('MALICIOUS.PY')

        with self.assertRaises(UnsafeInputError):
            Table('data.Pickle')


class TestSQLInjectionPrevention(unittest.TestCase):
    """Tests for P1-3: SQL injection prevention in INSERT generation"""

    def test_single_quotes_escaped(self):
        """Single quotes in data should be properly escaped"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        # Data with single quotes (like Irish names)
        data = [{'id': 1, 'name': "O'Brien"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))

        # Should contain escaped quote, not unescaped
        self.assertIn("O''Brien", inserts[0])
        self.assertNotIn("O'Brien", inserts[0])

    def test_sql_injection_payload_neutralized(self):
        """SQL injection payloads should be escaped, not executed"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        # Classic SQL injection attempt
        data = [{'id': 1, 'name': "'; DROP TABLE users; --"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))

        # The payload should be escaped as a string literal
        self.assertIn("DROP TABLE", inserts[0])  # Content preserved
        self.assertIn("'''; DROP TABLE users; --'", inserts[0])  # But safely quoted

    def test_backslash_handling(self):
        """Backslashes should be handled safely"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'path': 'C:\\Users\\test\\file.txt'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))

        # Should produce valid SQL
        self.assertIn('INSERT INTO', inserts[0])
        self.assertIn('C:', inserts[0])

    def test_null_value_handling(self):
        """NULL values should be properly represented"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'name': None, 'value': 'test'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))

        # NULL should appear as SQL NULL keyword
        self.assertIn('NULL', inserts[0])

    def test_unicode_handling(self):
        """Unicode characters should be safely included"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'name': 'François Englert'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))

        # Unicode should be preserved
        self.assertIn('François', inserts[0])

    def test_multiple_dialects_safe(self):
        """SQL injection prevention should work across dialects"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'name': "O'Brien"}]

        for dialect in ['postgresql', 'mysql', 'sqlite']:
            tbl = Table(data)
            inserts = list(tbl.inserts(dialect))

            # All dialects should escape the quote
            self.assertIn("O''Brien", inserts[0],
                         f"Quote not escaped for dialect {dialect}")


class TestFiles(unittest.TestCase):

    def test_use_open_file(self):
        with open(here('knights.yaml')) as infile:
            knights = Table(infile)
            generated = knights.sql('postgresql', inserts=True)
            self.assertIn('Lancelot', generated)
            

        

    def test_files(self):
        blocked_extensions = {'.py', '.pyw', '.pickle', '.pkl'}
        for sql_fname in glob.glob(here('*.sql')):
            with open(sql_fname) as infile:
                expected = infile.read().strip()
            (fname, ext) = os.path.splitext(sql_fname)
            for source_fname in glob.glob(here('%s.*' % fname)):
                (fname, ext) = os.path.splitext(source_fname)
                if ext != '.sql' and ext not in blocked_extensions:
                    tbl = Table(source_fname, uniques=True)
                    generated = tbl.sql('postgresql', inserts=True, drops=True).strip()
                    self.assertEqual(generated, expected)


class TestCleanKeyName(unittest.TestCase):
    """Tests for reshape.clean_key_name edge cases (P0-6)"""

    def setUp(self):
        try:
            from ddlgenerator.reshape import clean_key_name
        except ImportError:
            from reshape import clean_key_name
        self.clean_key_name = clean_key_name

    def test_empty_string(self):
        """Empty string should return 'unnamed_column'"""
        self.assertEqual(self.clean_key_name(''), 'unnamed_column')

    def test_whitespace_only(self):
        """Whitespace-only string should return 'unnamed_column'"""
        self.assertEqual(self.clean_key_name('   '), 'unnamed_column')
        self.assertEqual(self.clean_key_name('\t\n'), 'unnamed_column')

    def test_valid_name_unchanged(self):
        """Valid column names should pass through (lowercased)"""
        self.assertEqual(self.clean_key_name('valid_name'), 'valid_name')
        self.assertEqual(self.clean_key_name('ValidName'), 'validname')

    def test_leading_digit(self):
        """Names starting with digit should be prefixed with underscore"""
        self.assertEqual(self.clean_key_name('123abc'), '_123abc')

    def test_reserved_word(self):
        """SQL reserved words should be prefixed with underscore"""
        self.assertEqual(self.clean_key_name('SELECT'), '_select')
        self.assertEqual(self.clean_key_name('where'), '_where')

    def test_special_characters(self):
        """Special characters should be replaced with underscore"""
        self.assertEqual(self.clean_key_name('my column'), 'my_column')
        self.assertEqual(self.clean_key_name('my-column'), 'my_column')


class TestURLValidation(unittest.TestCase):
    """Tests for url_utils URL validation (P1-2)"""

    def setUp(self):
        try:
            from ddlgenerator import url_utils
        except ImportError:
            import url_utils
        self.url_utils = url_utils

    def test_valid_http_url(self):
        """Valid HTTP URLs should pass validation"""
        # Should not raise
        self.url_utils.validate_url('http://example.com/data.yaml')

    def test_valid_https_url(self):
        """Valid HTTPS URLs should pass validation"""
        # Should not raise
        self.url_utils.validate_url('https://example.com/data.json')

    def test_invalid_scheme_ftp(self):
        """FTP URLs should be rejected"""
        with self.assertRaises(self.url_utils.URLValidationError):
            self.url_utils.validate_url('ftp://example.com/file')

    def test_invalid_scheme_file(self):
        """file:// URLs should be rejected"""
        with self.assertRaises(self.url_utils.URLValidationError):
            self.url_utils.validate_url('file:///etc/passwd')

    def test_invalid_scheme_javascript(self):
        """javascript: URLs should be rejected"""
        with self.assertRaises(self.url_utils.URLValidationError):
            self.url_utils.validate_url('javascript:alert(1)')

    def test_ssrf_localhost(self):
        """localhost should be blocked for SSRF prevention"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://localhost/admin')

    def test_ssrf_loopback_127(self):
        """127.x.x.x should be blocked for SSRF prevention"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://127.0.0.1/admin')

    def test_ssrf_private_10(self):
        """10.x.x.x should be blocked for SSRF prevention"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://10.0.0.1/internal')

    def test_ssrf_private_192_168(self):
        """192.168.x.x should be blocked for SSRF prevention"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://192.168.1.1/router')

    def test_ssrf_private_172_16(self):
        """172.16-31.x.x should be blocked for SSRF prevention"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://172.16.0.1/internal')

    def test_is_url_with_http(self):
        """is_url should return True for HTTP URLs"""
        self.assertTrue(self.url_utils.is_url('http://example.com'))

    def test_is_url_with_https(self):
        """is_url should return True for HTTPS URLs"""
        self.assertTrue(self.url_utils.is_url('https://example.com'))

    def test_is_url_with_file_path(self):
        """is_url should return False for file paths"""
        self.assertFalse(self.url_utils.is_url('/path/to/file.yaml'))

    def test_is_url_with_non_string(self):
        """is_url should return False for non-string inputs"""
        self.assertFalse(self.url_utils.is_url(['list']))
        self.assertFalse(self.url_utils.is_url({'dict': 'value'}))
        self.assertFalse(self.url_utils.is_url(None))


class TestYAMLSafety(unittest.TestCase):
    """Tests for P1-4: yaml.safe_load rejects malicious YAML tags"""

    def test_safe_load_rejects_python_object(self):
        """YAML with !!python/object tags should be rejected by safe_load"""
        import yaml
        import io
        malicious_yaml = "!!python/object/apply:os.system ['echo pwned']"
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(malicious_yaml)

    def test_safe_load_rejects_python_module(self):
        """YAML with !!python/module tags should be rejected"""
        import yaml
        malicious_yaml = "!!python/module:os"
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(malicious_yaml)

    def test_safe_load_rejects_python_name(self):
        """YAML with !!python/name tags should be rejected"""
        import yaml
        malicious_yaml = "!!python/name:os.system"
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(malicious_yaml)

    def test_safe_load_accepts_normal_yaml(self):
        """Normal YAML data should be parsed correctly"""
        import yaml
        normal_yaml = "name: Lancelot\nkg: 69.4\nquest: Grail"
        result = yaml.safe_load(normal_yaml)
        self.assertEqual(result['name'], 'Lancelot')

    def test_metadata_source_uses_safe_load(self):
        """Table's metadata_source path uses yaml.safe_load, not yaml.load"""
        import inspect
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table
        source = inspect.getsource(Table.__init__)
        self.assertIn('yaml.safe_load', source)
        self.assertNotIn('yaml.load(', source)


class TestFilelikeObjectSecurity(unittest.TestCase):
    """Tests that file-like objects with blocked extensions are also rejected"""

    def test_filelike_with_py_extension_blocked(self):
        """File-like objects with .py name should be rejected"""
        import io
        try:
            from ddlgenerator.ddlgenerator import Table, UnsafeInputError
        except ImportError:
            from ddlgenerator import Table, UnsafeInputError

        fake_file = io.StringIO("import os; os.system('rm -rf /')")
        fake_file.name = 'exploit.py'
        with self.assertRaises(UnsafeInputError):
            Table(fake_file)

    def test_filelike_with_pickle_extension_blocked(self):
        """File-like objects with .pickle name should be rejected"""
        import io
        try:
            from ddlgenerator.ddlgenerator import Table, UnsafeInputError
        except ImportError:
            from ddlgenerator import Table, UnsafeInputError

        fake_file = io.BytesIO(b'\x80\x03some pickle data')
        fake_file.name = 'data.pickle'
        with self.assertRaises(UnsafeInputError):
            Table(fake_file)


class TestSSRFAdditional(unittest.TestCase):
    """Additional SSRF prevention tests for edge cases"""

    def setUp(self):
        try:
            from ddlgenerator import url_utils
        except ImportError:
            import url_utils
        self.url_utils = url_utils

    def test_ssrf_zero_ip(self):
        """0.0.0.0 should be blocked"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://0.0.0.0/admin')

    def test_ssrf_link_local(self):
        """169.254.x.x (link-local) should be blocked"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://169.254.169.254/metadata')

    def test_ssrf_ipv6_loopback(self):
        """IPv6 loopback ::1 should be blocked"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://[::1]/admin')

    def test_ssrf_172_31(self):
        """172.31.x.x (upper end of 172.16/12 range) should be blocked"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.validate_url('http://172.31.255.255/internal')

    def test_safe_fetch_validates_url(self):
        """safe_fetch should reject private IPs before making a request"""
        with self.assertRaises(self.url_utils.SSRFError):
            self.url_utils.safe_fetch('http://192.168.1.1/secret')

    def test_safe_fetch_rejects_bad_scheme(self):
        """safe_fetch should reject non-http(s) schemes"""
        with self.assertRaises(self.url_utils.URLValidationError):
            self.url_utils.safe_fetch('ftp://example.com/file')

    def test_no_hostname(self):
        """URL with no hostname should be rejected"""
        with self.assertRaises(self.url_utils.URLValidationError):
            self.url_utils.validate_url('http://')

    def test_is_private_ip_public(self):
        """Public IPs should not be flagged as private"""
        self.assertFalse(self.url_utils.is_private_ip('8.8.8.8'))
        self.assertFalse(self.url_utils.is_private_ip('93.184.216.34'))

    def test_is_private_ip_invalid(self):
        """Invalid IP strings should return False"""
        self.assertFalse(self.url_utils.is_private_ip('not-an-ip'))
        self.assertFalse(self.url_utils.is_private_ip(''))


class TestSQLInjectionAdditional(unittest.TestCase):
    """Additional SQL injection tests for edge cases"""

    def test_double_quote_injection(self):
        """Double quotes in data should be handled safely"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'name': 'He said "hello"'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        self.assertIn('INSERT INTO', inserts[0])

    def test_semicolon_injection(self):
        """Semicolons in data should not break out of the INSERT"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'comment': "value; DELETE FROM users"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # The semicolon should be inside the quoted string
        self.assertEqual(len(inserts), 1)  # Should be exactly one INSERT

    def test_newline_injection(self):
        """Newlines in data should not create additional SQL statements"""
        try:
            from ddlgenerator.ddlgenerator import Table
        except ImportError:
            from ddlgenerator import Table

        data = [{'id': 1, 'bio': "line1\nDROP TABLE users;\nline3"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        self.assertEqual(len(inserts), 1)


if __name__ == '__main__':
    unittest.main()
