#!/usr/bin/env python

import httplib2
import pprint
import sys
import logging, logging.handlers
import json
import os
import thread
from apiclient.discovery import build
from apiclient.http import MediaFileUpload, HttpRequest, BatchHttpRequest
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.client import Credentials
from apiclient import errors

class NoUserIdException:
    """
    ....
    """

class GoogleServiceProvider:

    def __init__(self,**kwargs):
        ### we need to put these in a try/except statement because these 
        ### keys are not always present in **kwargs (i.e. when we do not need to generate the refresh_token again)
        try:
            self.CLIENT_ID = kwargs['CLIENT_ID']
        except KeyError:
            self.CLIENT_ID = None
        try:
            self.CLIENT_SECRET = kwargs['CLIENT_SECRET']
        except KeyError:
            self.CLIENT_SECRET = None

        self.jsonfile = kwargs['jsonfile']
        # Check https://developers.google.com/drive/scopes for all available scopes
        self.OAUTH_SCOPES = kwargs['OAUTH_SCOPES']

        # Redirect URI for installed apps
        self.REDIRECT_URI = kwargs['REDIRECT_URI'] or None
        # default parent directory for the google drive directory structure
        self.DEFAULT_PARENT = kwargs['DEFAULT_PARENT'] or None
        t = (self.CLIENT_ID, self.CLIENT_SECRET, self.jsonfile, self.OAUTH_SCOPES, self.REDIRECT_URI)

        self.batch = BatchHttpRequest()

    def get_trace(exc):
            import traceback
            self.logger("An exception occured: %s" % e)
            traceback.print_exc(file=sys.stdout)

    def get_user_info(self,credentials):
        """Send a request to the UserInfo API to retrieve the user's information.
        Args:
          credentials: oauth2client.client.OAuth2Credentials instance to authorize the
                       request.
        Returns:
          User information as a dict.
        """
        user_info_service = build(
            serviceName='oauth2', version='v2',
            http=credentials.authorize(httplib2.Http()))
        user_info = None
        try:
            user_info = user_info_service.userinfo().get().execute()
        except Exception, e:
            print('An error occurred: %s', e)
        if user_info and user_info.get('id'):
            return user_info
        else:
            raise NoUserIdException()

    def store_credentials(self,user_id, credentials):
        """Store OAuth 2.0 credentials in the application's database.

        This function stores the provided OAuth 2.0 credentials using the user ID as
        key.

        Args:
          user_id: User's ID.
          credentials: OAuth 2.0 credentials to store.
        Raises:
          NotImplemented: This function has not been implemented.
        """
        # TODO: Implement this function to work with your database.
        #       To retrieve a Json representation of the credentials instance, call the
        #       credentials.to_json() method.
        data = credentials.to_json()
        with open(self.jsonfile, 'w') as outfile:
            json.dump(data,outfile)
            outfile.close()

    def get_stored_credentials(self,user_id):
        """Retrieved stored credentials for the provided user ID.

        Args:
          user_id: User's ID.
        Returns:
          Stored oauth2client.client.OAuth2Credentials if found, None otherwise.
        Raises:
          NotImplemented: This function has not been implemented.
        """
        # TODO: Implement this function to work with your database.
        #       To instantiate an OAuth2Credentials instance from a Json
        #       representation, use the oauth2client.client.Credentials.new_from_json
        #       class method.
        with open(self.jsonfile, 'r') as infile:
            data = json.loads(infile.read())
            credentials = Credentials.new_from_json(data)
        if credentials:
            return credentials
        else:
            print("Please check credstore.json file %s" % infile)

    def get_refresh_token(self,CLIENT_ID=None,CLIENT_SECRET=None):

        # Run through the OAuth flow and retrieve credentials
        flow = OAuth2WebServerFlow(self.CLIENT_ID, self.CLIENT_SECRET, self.OAUTH_SCOPES, self.REDIRECT_URI)
        authorize_url = flow.step1_get_authorize_url()
        print('Go to the following link in your browser: %s' % authorize_url)
        code = raw_input('Enter verification code: ').strip()
        credentials = flow.step2_exchange(code)

        if credentials.refresh_token is not None:
            # user_info = self.get_user_info(credentials)
            # email_address = user_info.get('email')
            # user_id = user_info.get('id')
            # print("received user info: %s " % user_info)
            print("received token: %s" % credentials.refresh_token)
            token = credentials.refresh_token

            ##
            self.store_credentials(1,credentials)
            ##

            return credentials
        else:
            print("no refresh token received %s" % credentials)

    # Create an httplib2.Http object and authorize it with our credentials
    def build_service(self,credentials):
        """Build a Drive service object.
        Args:
        credentials: OAuth 2.0 credentials.
        Returns:
        Drive service object.
        """
        http = httplib2.Http()
        http = credentials.authorize(http)
        try:
            drive_service = build('drive', 'v2', http=http)
            t = (http, drive_service)
            if drive_service is not None:
                return t
        except Exception, e:
            import traceback
            print("An exception occured instantiating GDrive object: %s" % e)
            traceback.print_exc(file=sys.stdout)

    def upload_file(self,filename,fullpath, drive_service, body):
        """
        returns an instance of the file if successful or None
        """
        fisier = None
        for retry in range(5):
            try:
                media_body = MediaFileUpload(fullpath, mimetype=body['mimeType'], chunksize=1048576, resumable=False)
                fisier = drive_service.files().insert(body=body, media_body=media_body).execute()
            except Exception as e:
                import traceback
                print("Something went wrong uploading the file, retrying: %s %s" % (e, body))
                traceback.print_exc(file=sys.stdout)
                import time
                time.sleep(2)
                continue
            break
        return(fisier)

    def create_folder(self,drive_service,body):
        folder = None
        for retry in range(5):
            try:
                folder = drive_service.files().insert(body=body).execute()
                ## we also need to set the new parent_id here ( since it's a folder, it most likely contains files
            except Exception as e:
                import traceback
                print("Something went wrong creating the folder, retrying: %s" % e)
                traceback.print_exc(file=sys.stdout)
                continue
            break
        return folder

    def get_file_instance(self,service, file_id):
        """Print a file's metadata.
        Args:
          service: Drive API service instance.
          file_id: ID of the file to print metadata for.
        """
        try:
            file = service.files().get(fileId=file_id).execute()
            print('Title: %s' % file['title'])
            print('MIME type: %s' % file['mimeType'])
        except errors.HttpError, error:
            print('An error occurred: %s' % error)

    def retrieve_all_files(self,service):
        """Retrieve a list of File resources.
        Args:
          service: Drive API service instance.
        Returns:
          List of File resources.
        """
        result = []
        page_token = None
        while True:
            try:
                param = {}
                if page_token:
                    param['pageToken'] = page_token
                files = service.files().list().execute()
                result.extend(files['items'])
                page_token = files.get('nextPageToken')
                if not page_token:
                    break
            except Exception, error:
                print('An error occured: %s' % error)
                break
        return result

    def query_entity(self,service,q,rec=False):
        """
        service = google drive service instance
        q = query set 
        returns an instance/list of filename or None if not found
        """
        print("entered query_entity() %s" % q)
        results = []
        files = service.files().list(q=q).execute()['items']
        if files:
            for fi in files:
                try:
                    results.append(service.files().get(fileId=fi['id']).execute() )
                except apiclient.errors.HttpError as e:
                    print("Something went wrong with the file query: %s " % e)
        return results

    def update_file(self,service,new_content,file_id,new_body=None):
        """
        new_body is set only when file metadata is changing
        """
        try:
            fisier = service.files().get(fileId=file_id).execute()
            media_body = MediaFileUpload(new_content, mimetype=new_body['mimeType'], resumable=True)
            updated_file = service.files().update(fileId=file_id, body=fisier, media_body=media_body).execute()
        except errors.HttpError as error:
            print("Something went wrong updating the file: %s" % error)
            return None
        return updated_file



    def download_files(self,service,list_of_files,target_dir,sync=False):
        """
        takes a gdrive service instance together with a list of file instances 
        to be downloaded
        file instances can be obtained with query_entity()
        """
        urls = {}; keys = []; values = []
        for fisier in list_of_files:
            keys.append(fisier.get('downloadUrl'))
            values.append(fisier.get('description'))
        urls = dict(zip(keys,values))
        
        results = []
        for url, filename in urls.iteritems():
            if url is None:
                if filename is None:
                    filename = ""
                print("Filename with no download URL: %s" % filename) # folders have no download URL
                if not os.path.exists(os.path.abspath(target_dir+"/"+filename)):
                    print("Creating dir: %s" % os.path.dirname(os.path.abspath(target_dir+"/"+filename)))
                    os.makedirs(os.path.dirname(os.path.abspath(target_dir+"/"+filename)))
                continue
            else:
                resp, content = service._http.request(url)
            if resp.status == 200:
                try:
                    if not os.path.exists(os.path.dirname(os.path.abspath(target_dir+"/"+filename))):
                        print("Creating dir: %s" % os.path.dirname(os.path.abspath(target_dir+"/"+filename)))
                        os.makedirs(os.path.dirname(os.path.abspath(target_dir+"/"+filename)))
                    filetoopen=os.path.abspath(target_dir+"/"+filename)
                    print("Writing to: %s" % filetoopen)
                    with open(filetoopen, 'w') as f:
                        f.write(content)    
                        f.close()
                        results.append(filename)
                except Exception as e:
                    print("Something went wrong writing the file: %s" % e)
            else:
                print("File not found: %s" % resp.status)
                continue
        return results