import io,unittest,urllib.error
from types import SimpleNamespace
from unittest.mock import patch
from e7gw_source import read_public_html

class Response(io.BytesIO):
 headers=SimpleNamespace(get_content_type=lambda:'text/html')

class RetryTests(unittest.TestCase):
 def test_temporary_handshake_timeout_is_retried_once(self):
  opener=SimpleNamespace(open=__import__('unittest.mock').mock.Mock(side_effect=[urllib.error.URLError(TimeoutError('handshake timed out')),Response(b'<html>ok</html>')]))
  with patch('e7gw_source.urllib.request.build_opener',return_value=opener),patch('e7gw_source.time.sleep'):
   self.assertEqual(read_public_html('https://e7gw.xyz/counters'),'<html>ok</html>')
  self.assertEqual(opener.open.call_count,2)
 def test_access_denial_is_not_retried(self):
  opener=SimpleNamespace(open=__import__('unittest.mock').mock.Mock(side_effect=urllib.error.HTTPError('https://e7gw.xyz/counters',403,'Denied',{},None)))
  with patch('e7gw_source.urllib.request.build_opener',return_value=opener):
   with self.assertRaises(urllib.error.HTTPError):read_public_html('https://e7gw.xyz/counters')
  self.assertEqual(opener.open.call_count,1)
