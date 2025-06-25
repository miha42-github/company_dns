import logging
from os import path
from .db_functions import DbFunctions
from .prepare_sic_data import ExtractSicData
from .prepare_edgar_data import ExtractEdgarData
from .prepare_uk_sic_data import ExtractUkSicData
from .prepare_international_sic_data import ExtractInternationalSicData
from .prepare_eu_sic_data import ExtractEuSicData  # Add import for EU SIC data

class MakeDb:
    """Create the database cache file
    """
    def __init__(self, **kwargs):
        """Initialize the module
        """
        global logger
        logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=kwargs.get('verbose', logging.WARNING))
        logger = logging.getLogger(__file__)
        self.operating_path = kwargs.get('operating_path', './')
        self.config = kwargs.get('config', {"db_control": {"DB_NAME": "company_dns.db"}})
        self.sic_extractor = ExtractSicData(config=self.config)
        self.edgar_extractor = ExtractEdgarData(config=self.config)
        self.uk_sic_extractor = ExtractUkSicData(config=self.config)
        self.international_sic_extractor = ExtractInternationalSicData(config=self.config)
        self.eu_sic_extractor = ExtractEuSicData(config=self.config)  # Add EU SIC extractor
        self.db_functions = DbFunctions(operating_path=self.operating_path, config=self.config)

# -------------------------------------------------------------- #
# BEGIN: Standard Idustry Classification (SIC) database cache functions

    def _create_sic_tables(self, c, conn):
        """Create the SIC tables
        """
        logger.info('Creating tables for the SIC data.')
        c.execute('CREATE TABLE sic (division text, major_group text, industry_group text, sic text, description text)')
        c.execute('CREATE TABLE industry_groups (division text, major_group text, industry_group text, description text)')
        c.execute('CREATE TABLE major_groups (division text, major_group text, description text)')
        c.execute('CREATE TABLE divisions (division text, description text, full_description text)')
        conn.commit()

    def _insert_sic_data(self, c, conn, sic_data):
        """Load the SIC data into the DB cache file
        """
        logger.info('Adding sic data to the companies db cache file.')
        num = len(sic_data['divisions']) + len(sic_data['major_groups']) + len(sic_data['industry_groups']) + len(sic_data['sics'])
        c.executemany('INSERT INTO divisions VALUES (?,?,?)', sic_data['divisions'])
        c.executemany('INSERT INTO major_groups VALUES (?,?,?)', sic_data['major_groups'])
        c.executemany('INSERT INTO industry_groups VALUES (?,?,?,?)', sic_data['industry_groups'])
        c.executemany('INSERT INTO sic VALUES (?,?,?,?,?)', sic_data['sics'])
        conn.commit()
        return num

    def _build_sic_db(self, c, conn):
        """Build the SIC data in the DB cache file
        """
        logger.info('Creating the SIC tables, and loading the SIC data into the db cache file.')
        self._create_sic_tables(c, conn)
        sic_data = self.sic_extractor.extract_data()
        num = self._insert_sic_data(c, conn, sic_data)
        return num
    
    # END: Standard Idustry Classification (SIC) database cache functions
    # -------------------------------------------------------------- #
    
    # -------------------------------------------------------------- #
    # BEGIN: UK Standard Industry Classification (SIC) database cache functions

    def _create_uk_sic_tables(self, c, conn):
        """Create the UK SIC tables
        """
        logger.info('Creating tables for the UK SIC data.')
        c.execute('CREATE TABLE uk_sic (sic_code text, description text)')
        conn.commit()

    def _insert_uk_sic_data(self, c, conn, uk_sic_data):
        """Load the UK SIC data into the DB cache file
        """
        logger.info('Adding UK SIC data to the companies db cache file.')
        num = len(uk_sic_data['uk_sic'])
        c.executemany('INSERT INTO uk_sic VALUES (?,?)', uk_sic_data['uk_sic'])
        conn.commit()
        return num

    def _build_uk_sic_db(self, c, conn):
        """Build the UK SIC data in the DB cache file
        """
        logger.info('Creating the UK SIC tables, and loading the UK SIC data into the db cache file.')
        self._create_uk_sic_tables(c, conn)
        uk_sic_data = self.uk_sic_extractor.extract_data()
        num = self._insert_uk_sic_data(c, conn, uk_sic_data)
        return num
    
    # END: UK Standard Industry Classification (SIC) database cache functions
    # -------------------------------------------------------------- #
    
    # -------------------------------------------------------------- #
    # BEGIN: EDGAR dabase cache functions

    def _create_companies_table(self, c, conn):
        """Create the company table in the DB
        """
        logger.info('Creating table to store company data in the db cache file.')
        c.execute('CREATE TABLE companies (cik int, name text, year int, month int, day int, accession text, form text)')
        conn.commit()


    def _load_companies(self, c, conn, companies):
        """Load the EDGAR company data into the DB cache file
        """
        logger.info('Adding company data to the companies db cache file.')
        num = len(companies)
        c.executemany('INSERT INTO companies VALUES (?,?,?,?,?,?,?)', companies)
        conn.commit()
        return num
    
    def _build_edgar_db(self, c, conn):
        """Build the EDGAR data in the DB cache file
        """
        logger.info('Creating the companies table, and loading the companies data into the db cache file.')
        self._create_companies_table(c, conn)
        companies, total = self.edgar_extractor.extract_data()
        num = self._load_companies(c, conn, companies)
        return num

    # END: EDGAR dabase cache functions
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # BEGIN: International Standard Industry Classification (ISIC) database cache functions

    def _create_international_sic_tables(self, c, conn):
        """Create the International SIC tables
        """
        logger.info('Creating tables for the International SIC data.')
        c.execute('CREATE TABLE isic_sections (section_code text, description text)')
        c.execute('CREATE TABLE isic_divisions (division_code text, description text, section_code text)')
        c.execute('CREATE TABLE isic_groups (group_code text, description text, division_code text, section_code text)')
        c.execute('CREATE TABLE isic_classes (class_code text, description text, group_code text, division_code text, section_code text)')
        conn.commit()

    def _insert_international_sic_data(self, c, conn, isic_data):
        """Load the International SIC data into the DB cache file
        """
        logger.info('Adding International SIC data to the companies db cache file.')
        num = len(isic_data['sections']) + len(isic_data['divisions']) + len(isic_data['groups']) + len(isic_data['classes'])
        
        c.executemany('INSERT INTO isic_sections VALUES (?,?)', isic_data['sections'])
        c.executemany('INSERT INTO isic_divisions VALUES (?,?,?)', isic_data['divisions'])
        c.executemany('INSERT INTO isic_groups VALUES (?,?,?,?)', isic_data['groups'])
        c.executemany('INSERT INTO isic_classes VALUES (?,?,?,?,?)', isic_data['classes'])
        
        conn.commit()
        return num

    def _build_international_sic_db(self, c, conn):
        """Build the International SIC data in the DB cache file
        """
        logger.info('Creating the International SIC tables, and loading the International SIC data into the db cache file.')
        self._create_international_sic_tables(c, conn)
        isic_data = self.international_sic_extractor.extract_data()
        num = self._insert_international_sic_data(c, conn, isic_data)
        return num

    # END: International Standard Industry Classification (ISIC) database cache functions
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # BEGIN: EU Standard Industry Classification (NACE) database cache functions

    def _create_eu_sic_tables(self, c, conn):
        """Create the EU SIC tables
        """
        logger.info('Creating tables for the EU SIC data.')
        c.execute('CREATE TABLE eu_sic_sections (section_code text, description text)')
        c.execute('CREATE TABLE eu_sic_divisions (division_code text, description text, section_code text)')
        c.execute('CREATE TABLE eu_sic_groups (group_code text, description text, division_code text, section_code text)')
        c.execute('CREATE TABLE eu_sic_classes (class_code text, description text, group_code text, division_code text, section_code text)')
        conn.commit()

    def _insert_eu_sic_data(self, c, conn, eu_sic_data):
        """Load the EU SIC data into the DB cache file
        """
        logger.info('Adding EU SIC data to the companies db cache file.')
        num = len(eu_sic_data['sections']) + len(eu_sic_data['divisions']) + len(eu_sic_data['groups']) + len(eu_sic_data['classes'])
        
        c.executemany('INSERT INTO eu_sic_sections VALUES (?,?)', eu_sic_data['sections'])
        c.executemany('INSERT INTO eu_sic_divisions VALUES (?,?,?)', eu_sic_data['divisions'])
        c.executemany('INSERT INTO eu_sic_groups VALUES (?,?,?,?)', eu_sic_data['groups'])
        c.executemany('INSERT INTO eu_sic_classes VALUES (?,?,?,?,?)', eu_sic_data['classes'])
        
        conn.commit()
        return num

    def _build_eu_sic_db(self, c, conn):
        """Build the EU SIC data in the DB cache file
        """
        logger.info('Creating the EU SIC tables, and loading the EU SIC data into the db cache file.')
        self._create_eu_sic_tables(c, conn)
        eu_sic_data = self.eu_sic_extractor.extract_data()
        num = self._insert_eu_sic_data(c, conn, eu_sic_data)
        return num

    # END: EU Standard Industry Classification (NACE) database cache functions
    # -------------------------------------------------------------- #

    def build_db(self):
        """
        Perform all operations needed to build the DB cache file

        ;param file_name: name of the tab file to pull into create the cache

        """
        total = 0

        logger.info('Initiating the db_cache build.')
        (my_conn, my_cursor) = self.db_functions.create_db()

        # Build and load the EDGAR data
        total += self._build_edgar_db(my_cursor, my_conn)

        # Build and load the SIC data
        total += self._build_sic_db(my_cursor, my_conn)
        
        # Build and load the UK SIC data
        total += self._build_uk_sic_db(my_cursor, my_conn)
        
        # Build and load the International SIC data
        total += self._build_international_sic_db(my_cursor, my_conn)
        
        # Build and load the EU SIC data
        total += self._build_eu_sic_db(my_cursor, my_conn)

        # Log the total number of entries in the database
        logger.info('Total number of entries in the database cache file: %s.', total)

        # Close the database
        self.db_functions.close_db(my_conn)
        # Create the file that controls the reindexing
        open(self.operating_path + self.config['db_control']['DB_EXISTS'], 'w').close()
        return True, "Created the database cache with " + str(total) + " entries stored in " + self.config['db_control']['DB_NAME']