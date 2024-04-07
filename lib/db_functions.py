import sqlite3
import logging
import os

class DbFunctions:
    """Basic database functions
    """

    def __init__(self, **kwargs):
        """Initialize the module
        """
        global logger
        logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=kwargs.get('verbose', logging.WARNING))
        logger = logging.getLogger(__file__)
        self.operating_path = kwargs.get('operating_path', './')
        self.config = kwargs.get('config', {"db_control": {"DB_NAME": "companies.db"}})

    def create_db(self):
        """Create an empty database cache file and return the DB cursor
        """
        logger.info('Attaching to the database file %s.', self.operating_path + self.config['db_control']['DB_NAME'])
        conn = sqlite3.connect(self.config['db_control']['DB_NAME'])
        c = conn.cursor()
        conn.commit()
        return conn, c

    def close_db(self, conn):
        """Close the DB cache file and connection
        """
        logger.info('Closing the connection to the database file.')
        conn.close()

    def open_db(self):
        """Open the database cache file and return the DB cursor
        """
        logger.info('Attaching to the database file %s.', self.operating_path + self.config['db_control']['DB_NAME'])
        conn = sqlite3.connect(self.config['db_control']['DB_NAME'])
        c = conn.cursor()
        return conn, c
    
    def clean_db(self):
        """Remove the DB Cache from the file system including the control file
        """
        logger.info('Cleaning up the db cache instance, %s, from the filesystem.', self.operating_path + self.config['db_control']['DB_NAME'])
        try:
            os.remove(self.operating_path + self.config['db_control']['DB_NAME'])
            os.remove(self.operating_path + self.config['db_control']['DB_EXISTS'])
        except FileNotFoundError:
            logger.warning('The supplied file names, %s and %s, for the db cache was not found.', self.config['db_control']['DB_NAME'], self.config['db_control']['DB_EXISTS'])
        return