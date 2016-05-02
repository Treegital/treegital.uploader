# -*- coding: utf-8 -*-

import ConfigParser
import cgi
import datetime
import hashlib
import logging
import os
import re
import shutil
import uuid

from os.path import join
from stat import ST_SIZE, ST_CTIME
from .ticket import UUID_ATM

RETRY = 10
CHUNKSIZE = 4096
INNER_ENCODING = 'utf-8'
HTTP_ENCODING = 'iso-8859-1'

logger = logging.getLogger('verification')
logger.setLevel(logging.INFO)


_filename_ascii_strip_re = re.compile(r'[^A-Za-z0-9_.-]')
_windows_device_files = (
    'CON', 'AUX', 'COM1', 'COM2', 'COM3',
    'COM4', 'LPT1', 'LPT2', 'LPT3', 'PRN', 'NUL')


def chunk_reader(fobj, chunk_size=CHUNKSIZE):
    """Generator that reads a file in chunks of bytes
    """
    while True:
        chunk = fobj.read(chunk_size)
        if not chunk:
            return
        yield chunk


def digest(fobj, hash=hashlib.sha1):
    hashobj = hash()
    for chunk in chunk_reader(fobj):
        hashobj.update(chunk)
    fobj.seek(0)
    return hashobj.digest()


def clean_filename(filename):
    """Borrowed from Werkzeug : http://werkzeug.pocoo.org/
    """
    if isinstance(filename, unicode):
        from unicodedata import normalize
        filename = normalize('NFKD', filename).encode('ascii', 'ignore')
    for sep in os.path.sep, os.path.altsep:
        if sep:
            filename = filename.replace(sep, ' ')
    filename = str(_filename_ascii_strip_re.sub('', '_'.join(
                   filename.split()))).strip('._')

    # on nt a couple of special files are present in each folder. We
    # have to ensure that the target file is not such a filename. In
    # this case we prepend an underline
    if os.name == 'nt' and filename and \
       filename.split('.')[0].upper() in _windows_device_files:
        filename = '_' + filename

    return filename


def ConfigParserManifest(object):

    def __init__(self, dest):
        self.dest = dest

    def write(self, *files):
        config = ConfigParser.RawConfigParser()
        for digest, filename in files:
            path = join(self.dest, digest)
            stats = os.stat(path)
            config.add_section(digest)
            config.set(written_fn, 'canonical_name', filename)
            config.set(written_fn, 'size', stats[ST_SIZE])
            config.set(written_fn, 'date', stats[ST_CTIME])

        with open(self.dest, 'wb') as configfile:
            config.write(configfile)

    def read(self):
        data = {}
        config = ConfigParser.ConfigParser()
        with open(self.dest, 'r') as configfile:
            config.readfp(open('defaults.cfg'))

        for section in config.sections():
            data[section] = dict(config.items(section))
            
        return data


def create_file(path, name):
    filepath = join(path, name)
    try:
        if not os.path.exists(filepath):
            return filepath
    except OSError, e:
        logger.error(e)
    return None


def create_directory(path):
    try:
        if not os.path.exists(path):
            os.makedirs(path)
        return path
    except OSError, e:
        return None


def persist_files(environ, destination):
    """Document me.
    """
    fields = cgi.FieldStorage(
        fp=environ['wsgi.input'], environ=environ, keep_blank_values=1)    

    # stored files on fs
    files = set()
    digests = set()

    for name in fields.keys():
        field = fields[name]
        if not isinstance(field, list):
            # handle multiple fields of same name (html5 uploads)
            field = [field]

        for item in field:
            if isinstance(item, cgi.FieldStorage) and item.filename:
                digested = digest(item.file)
                if digested not in digests:
                    digests.add(digested)
                    filename = clean_filename(item.filename)
                    path = join(destination, digested)
                    with open(path, 'w') as upload:
                        shutil.copyfileobj(item.file, upload)
                    files.append((digested, filename))

    return files


class FilesystemHandler(object):
    """Document me.
    """
    ignore = set(('MANIFEST',))
    
    def __init__(self, upload, namespace):
        self.__upload = upload
        self.namespace = namespace
        
    @property
    def upload_root(self):
        return join(self.__upload, self.namespace)

    def ticket_files(self, ticket):
        path = self.atm.get_path(ticket)
        for listed in os.listdir(path):
            if listed not in self.ignore:
                yield listed
                
    def upload(self, upload_node, environ):
        """The heart of the handler.
        """
        with tempfile.TemporaryDirectory() as tmpdirname:
            files = persist_files(environ, tmpdirname)
            destination = join(self.upload_root, upload_node)
            shutil.move(tmpdirname, destination)
        return destination, files
    

class Uploader(object):
    """the uploading application
    """
    def __init__(self, upload, namespace, atm=UUID_ATM):
        self.atm = atm
        self.fs_handler = FilesystemHandler(upload, namespace)
        self.mf_handler = ConfigParseManifest

    def __call__(self, environ, start_response):
        ticket = self.atm.generate()
        path = self.atm.get_path(ticket)
        dest, files = self.handler.upload(path, environ)
        manifest = self.mf_handler(dest)
        manifest.write(*files)
        status = '200 OK'
        response_headers = [('Content-type','text/plain')]
        start_response(status, response_headers)
        return [path for filename, path in files]


def upload_service(*global_conf, **local_conf):
    namespace = local_conf.get('namespace')
    tmpdir = local_conf.get('tmpdir')
    upload = local_conf.get('upload')

    return Uploader(tmpdir, upload, namespace)
