#!/usr/bin/env python
import pyinotify
import os, sys
import logging
import json
import thread, threading
import time, datetime
import hashlib
import mimetypes
import traceback

# google stuff
from ServiceProviders.Google import GoogleServiceProvider
from apiclient.http import BatchHttpRequest
from apiclient import errors

#logging stuff


class NotImplementedError(Exception):
    """mime.from_file(fp)
    Generic Exception for Placeholder Functions
    """

class GenericEventHandler(pyinotify.ProcessEvent):
    """
    define every possible event type here
    overloads methods in parent class
    """
    def process_IN_CREATE(self, event):
        self.logger.info("-> Creating: %s" % event.name)

    def process_IN_DELETE(self, event):
        self.logger.info("-> Removing: %s" % event.name)

    def process_default(self, event):
        self.logger.info("->Unknown event: %s" % event.maskname)

class GoogleEventHandler(pyinotify.ProcessEvent):
    """
    uploads to google drive
    """
    def __init__(self, options_dict, watch_descriptors):
        """
        options_dict contains all parameters necesary for 
        the GoogleServiceProvider.__init__() method.
        """
        self.sp = GoogleServiceProvider(**options_dict)
        self.credentials = self.sp.get_stored_credentials('testid')
        self.service = self.sp.build_service(self.credentials)

        self.http = self.service[0]
        self.service = self.service[1]

        self.options_dict = options_dict
        for key, value in watch_descriptors[0].items():
            if value == 1:
                self.protected_dir = key
        self.descriptors =  watch_descriptors
        self.descriptors_dict = {}
        for desc in self.descriptors:
            self.descriptors_dict.update(desc)

        ### logging stuff:

        self.logger = logging.getLogger('main')
        self.logger.setLevel(logging.DEBUG)
        # create console handler and set level to debug
        self.ch = logging.StreamHandler()
        self.ch.setLevel(logging.DEBUG)
        # create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            filename=options_dict['LOGFILE'])
        # add formatter to ch
        self.ch.setFormatter(formatter)
        # add ch to logger
        
        logging.addLevelName( logging.WARNING, "%s" % logging.getLevelName(logging.WARNING))
        logging.addLevelName( logging.ERROR, "%s" % logging.getLevelName(logging.ERROR))
        logging.addLevelName( logging.DEBUG, "%s" % logging.getLevelName(logging.DEBUG))
        logging.addLevelName( logging.INFO, "%s" % logging.getLevelName(logging.INFO))

        # we need this mutex for the files_dict dictionary
        self.mutex = threading.Lock()

        # this is by default the SyncThemAll folder on GoogleDrive
        if self.options_dict['DEFAULT_PARENT'] != 'root':
            self.default_pid = self.sp.query_entity(self.service,"title = '"+self.options_dict['DEFAULT_PARENT']+"'")[0]['id']
        else:
            self.default_pid = 'root'
            # this will have to be loaded from json
        ## the structure of the json is:
        """
        { 
            'folder_pathname' : 
                {
                    'files' : {
                               'file1': {'md5sum': None, 
                                        'ownId': None, 
                                        'parent':None,
                                        'alreadyUploaded': False,
                                        'alreadyUpdated': False,
                                        'upLoadinProgress': False, 
                                        'progressBar': int,
                                        'fullpath':None,
                                        'fileBody': {}, 
                                        'googleBody': {} } } },
                               'file2': {'md5sum': None, 
                                        'ownId': None,
                                        'parent':None,
                                        'alreadyUploaded': False,
                                        'alreadyUpdated': False, 
                                        'upLoadinProgress': False, 
                                        'progressBar': int,
                                        'fullpath':None,
                                        'fileBody': {}, 
                                        'googleBody': {} } } },
                               'file3': {'md5sum': None, 
                                        'ownId': None,
                                        'parent':None,
                                        'alreadyUploaded': False,
                                        'alreadyUpdated': False, 
                                        'upLoadinProgress': False, 
                                        'progressBar': int,
                                        'fullpath':None,
                                        'fileBody': {},
                                        'googleBody': {} } } } 
                               },
                    'parent': None
                    'alreadyCreated': False,
                    'alreadyUpdated':False,
                    'grive': {'own_google_id':None, 'parent_google_id': None }
                    'folderBody': {}
                    'googleMetaData': {}
                }, 
        }
        """
        self.jsonfile = self.options_dict['treefile']
        self.files_dict = {}
        if not os.path.exists(self.jsonfile):
            self.files_dict.update(self.descriptors_dict.fromkeys(self.descriptors_dict.keys(),
                                                                  {'files': {}, 'grive':{'own_google_id': None, 'parent_google_id': None}, 'folderBody':{}, 'googleMetaData':{} }))
        else:
            with open(self.jsonfile, 'r') as infile:
                try:
                    self.files_dict = json.loads(infile.read())
                    infile.close()
                except ValueError as e:
                    self.logger.info("Jsonfile %s not found or corrupted!\n Please remove, or stash it." % self.jsonfile)

        self.syncthread = thread.start_new_thread(self._save_to_json, ())
        self.filesyncthread = thread.start_new_thread(self._synchronize_files, ())
        # [thread.start_new_thread(self._synchronize_files, ()) for i in range(10)]

    def _save_to_json(self):
        while True:
            self.logger.info("%s save_to_json()" % datetime.datetime.now())
            try:
                # logging.debug("Opening %s" % self.jsonfile)
                with open(self.jsonfile,'w') as outfile:
                    # locking stuff here
                    try:
                        json.dump(self.files_dict, outfile)
                    except Exception as e:
                        self.logger.info("%s" % e)
                        # release lock here
                    outfile.close()
            except Exception as e:
                tb = traceback.self.logger.info_exc()
                t = (datetime.datetime.now(), tb, e)
                self.logger.info("%s" % t)
            time.sleep(10)

    def _synchronize_files(self):
        self.file_sp = GoogleServiceProvider(**self.options_dict)
        self.file_credentials = self.file_sp.get_stored_credentials('testid')
        self.file_service = self.file_sp.build_service(self.file_credentials)[1]

        while True:
            # self.logger.info("%s %s -> _synchronize_files() " % (datetime.datetime.now(), threading.current_thread()))
            for (fullpath, directory, file_list) in os.walk(self.protected_dir):
                try:
                    if fullpath not in self.files_dict.keys():
                        continue
                    for fisier in file_list:
                        fp = os.path.join(fullpath, fisier)
                        self.mutex.acquire()
                        if fisier not in self.files_dict[fullpath]['files']:
                            self.files_dict[fullpath]['files'][fisier] = {
                                'md5sum': hashlib.md5(open(fp).read()).hexdigest(),
                                'ownId': None,
                                'parent': fullpath,
                                'alreadyUploaded': False,
                                'alreadyUpdated': False,
                                'upLoadinProgress': False,
                                'progressBar': 0,
                                'fullpath': fp,
                                'fileBody': {
                                    'title': fisier,
                                    'description': fp,
                                    'mimeType': mimetypes.guess_type(fp)[0] or 'text/plain',
                                    'parents': [
                                        {
                                            "kind": "drive#parentReference",
                                            "id": None,
                                            }
                                    ],
                                    },
                                'googleBody': {},
                                }

                        if self.files_dict[fullpath]['files'][fisier]['alreadyUploaded']:
                            self.mutex.release()
                            continue

                        if os.path.getsize(fp) == 0:
                            self.logger.info("%s is 0 bytes in size, skipping" % fp)
                            self.mutex.release()
                            continue

                        if self.files_dict[fullpath]['grive']['own_google_id']:
                            self.files_dict[fullpath]['files'][fisier]['fileBody']['parents'][0]['id'] = self.files_dict[fullpath]['grive']['own_google_id']

                        if self.files_dict[fullpath]['grive']['own_google_id'] is None and fullpath in self.descriptors[0]:
                            self.files_dict[fullpath]['files'][fisier]['fileBody']['parents'][0]['id'] = self.default_pid

                        self.mutex.release()


                        for retry in range(5):
                            try:

                                self.logger.debug("Uploading file: %s" % fisier)
                                googleReturnBody = self.file_sp.upload_file(fisier,
                                                                self.files_dict[fullpath]['files'][fisier]['fullpath'],
                                                                self.file_service,
                                                                self.files_dict[fullpath]['files'][fisier]['fileBody'])
                                break
                            except Exception as e:
                                self.logger.error("%s" % e)
                                traceback.print_exc()

                        if googleReturnBody:
                            try:
                                self.mutex.acquire()
                                self.files_dict[fullpath]['files'][fisier]['googleBody'] = googleReturnBody
                                self.files_dict[fullpath]['files'][fisier]['ownId'] = googleReturnBody['id']
                                self.files_dict[fullpath]['files'][fisier]['alreadyUploaded'] = True
                                self.logger.info("Successfully uploaded file: %s " % fp)

                                self.mutex.release()

                            except KeyError as e:
                                self.logger.info("File has already been deleted from the filesytem: %s" % e)
                                self.mutex.release()
                                continue
                except IOError as e:
                    self.logger.info("File has already been deleted from the filesystem: %s " % e)
                    self.mutex.release()
                    continue
                # finally:
                #     # if self.mutex._is_owned():
                #     self.mutex.release()
            time.sleep(self.options_dict['FILE_SYNC_INTERVAL'])

        def callb(request_id, response, exception):
            """
            in case something went wrong, attempts to retransmit the batch request ( 5 times  )
            """
            t = (request_id, self.batch._requests, exception)
            def upd():
                self.files_dict[response['description']]['alreadyCreated'] = True
                self.files_dict[response['description']]['grive']['own_google_id'] = response['id']
                self.files_dict[response['description']]['googleMetaData'].update(response)
            if exception is not None:
                self.logger.info("Error occured during BatchHttpRequest %s" % (t,))

            else:
                self.mutex.acquire()
                upd()
                self.mutex.release()

        self.batch = BatchHttpRequest(callback=callb)

    def process_IN_CREATE(self, event):
        """
        triggered by pyinotify when a file is created
        it only updates FILES inside files_dict
        """
        t = {'event.pathname': event.pathname,
             'event.maskname': event.maskname,
             'event.wd': event.wd,
             'event.dir': event.dir }
        self.logger.info("-> Creating: %s" % t)
        parent = os.path.abspath(os.path.join(event.pathname, os.pardir))

        folderbody = {'files': {},
                      'parent': parent,
                      'alreadyCreated': False,
                      'alreadyUpdated':False,
                      'grive': {'own_google_id':None, 'parent_google_id': None },
                      'folderBody': {
                          'title': os.path.basename(event.pathname),
                          'description': event.pathname,
                          'mimeType': 'application/vnd.google-apps.folder',
                          "parents": [{
                                          "kind": "drive#parentReference",
                                          "id": None,
                                          }],
                          },
                      'googleMetaData': {}}

        if event.dir:
            # we populate the structure first
            self.mutex.acquire()
            try:
                if self.files_dict[event.pathname]['alreadyCreated']:
                    self.mutex.release()
                    return 0

            except KeyError as e:
                self.files_dict[event.pathname] = folderbody
                self.mutex.release()

            # let's get the parent id
            if parent != self.protected_dir and parent in self.files_dict.keys():
                pid = self.files_dict[parent]['grive']['own_google_id']
            else:
                pid = None
            if parent == self.protected_dir:
                pid = self.default_pid


            self.mutex.acquire()
            # update structure first
            self.files_dict[event.pathname]['grive']['parent_google_id'] = pid
            self.files_dict[event.pathname]['folderBody']['parents'][0]['id'] = pid
            self.mutex.release()

            self.mutex.acquire()
            own_id = self.sp.create_folder(self.service, self.files_dict[event.pathname]['folderBody'])
            self.mutex.release()

            if own_id:
                self.mutex.acquire()
                t = (own_id['id'], own_id['title'])
                self.logger.info("Acquired own_id and title: %s" % (t,))
                self.files_dict[event.pathname]['grive']['own_google_id'] = own_id['id']
                self.files_dict[event.pathname]['googleMetaData'] = own_id
                self.files_dict[event.pathname]['alreadyCreated'] = True
                self.mutex.release()


    def process_IN_DELETE(self, event):
        t = {'event.pathname': event.pathname,
             'event.maskname': event.maskname,
             'event.wd': event.wd,
             'event.dir': event.dir }
        self.logger.info("-> Removing: %s" % t)
        parent = os.path.abspath(os.path.join(event.pathname, os.pardir))
        if event.dir:
            self.mutex.acquire()
            #if parent in self.files_dict.keys() and self.files_dict[event.pathname]['grive']['own_google_id']:
            if self.files_dict[event.pathname]['grive']['own_google_id']:
                for retry in range(5):
                    try:
                        self.service.files().delete(fileId=self.files_dict[event.pathname]['grive']['own_google_id']).execute()
                    except errors.HttpError as e:
                        self.logger.info("%s" % e)
                        continue
            self.files_dict.pop(event.pathname)
            self.mutex.release()
        else:
            if parent in self.files_dict.keys():
                self.mutex.acquire()
                try:
                    if self.files_dict[parent]['files'][os.path.basename(event.pathname)]['ownId']:
                        for retry in range(5):
                            try:
                                self.service.files().delete(fileId=self.files_dict[parent]['files'][os.path.basename(event.pathname)]['ownId']).execute()
                                break
                            except errors.HttpError as e:
                                self.logger.info("%s" % e)
                                continue
                except KeyError as e:
                    self.mutex.release()
                    return 0 # parent folder has been deleted
                try:
                    self.files_dict[parent]['files'].pop(os.path.basename(event.pathname))
                except KeyError as e:
                    self.mutex.release()
                    return 0
                self.mutex.release()

    def process_IN_MODIFY(self, event):
        """
        used when updating files
        """
        t = {'event.pathname': event.pathname,
             'event.maskname': event.maskname,
             'event.wd': event.wd,
             'event.dir': event.dir }
        self.logger.info("-> Modified: %s" % t)
        parent = os.path.abspath(os.path.join(event.pathname, os.pardir))
        self.mutex.acquire()
        if event.name not in self.files_dict[parent]['files']:
            self.mutex.release()
            return 0
        try:
            if not event.dir:
                if hashlib.md5(open(event.pathname).read()).hexdigest() != self.files_dict[parent]['files'][event.name]['md5sum']:
                    self.files_dict[parent]['files'][event.name]['md5sum'] = hashlib.md5(open(event.pathname).read()).hexdigest()
            updated_file = self.sp.update_file(self.service, event.pathname, self.files_dict[parent]['files'][event.name]['ownId'],
                                               new_body=self.files_dict[parent]['files'][event.name]['fileBody'])
        except (KeyError, IOError) as e:
            self.mutex.release()
            self.logger.info("Modify error: %s" % e)
            return 0
        self.mutex.release()


    def __del__(self):
        self.sp = None
        self.credentials = None
        self.service = None
        self.logger.info("Shutting down %s" % self.__class__.__name__)
