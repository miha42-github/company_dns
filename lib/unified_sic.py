import sys
import logging
from typing import Dict, Any, Optional, List

# Import all SIC modules
from .sic import SICQueries
from .uk_sic import UKSICQueries
from .eu_sic import EuSICQueries
from .international_sic import InternationalSICQueries
from .japan_sic import JapanSICQueries

__author__ = "Michael Hay"
__copyright__ = "Copyright 2025, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Production"
__contact__ = 'https://github.com/miha42-github/company_dns'

# Package and data dependencies
# Start with empty data dependencies - we'll populate this dynamically
DEPENDENCIES = {
    'modules': {
        'sic': 'US SIC codes',
        'uk_sic': 'UK SIC codes',
        'eu_sic': 'EU SIC (NACE) codes',
        'international_sic': 'International SIC (ISIC) codes',
        'japan_sic': 'Japan SIC codes'
    },
    'data': {}
}

class UnifiedSICQueries:
    """A module that searches across all SIC implementations.
    """
    
    def __init__(
        self,
        db_file: str = './company_dns.db',
        name: str = 'unified_sic',
        description: str = 'A module to search across all SIC implementations.'
    ) -> None:
        # Database file path
        self.db_file = db_file
        
        # Naming helpers
        self.NAME = name
        self.DESC = description
        
        # Query object
        self.query: Optional[str] = None
        
        # Set up logging
        self.logger = logging.getLogger(self.NAME)
        
    def _safe_query(self) -> str:
        """Return a safe version of the query string, handling None values
        
        Returns:
            str: The query string or empty string if None
        """
        return "" if self.query is None else str(self.query)
        
    def search_all_descriptions(self) -> Dict[str, Any]:
        """Search across all SIC implementations for descriptions matching the query string.
        
        Returns:
            results (dict): A dictionary containing results from all SIC systems
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_results = {
            'results': [],
            'sources': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Track successful sources
        successful_sources = []
        
        # Combined dependencies - we'll collect these from each response
        combined_dependencies = {
            'modules': DEPENDENCIES['modules'].copy(),
            'data': {}
        }
        
        # 1. Query US SIC
        try:
            us_sic = SICQueries(db_file=self.db_file)
            us_sic.query = query_str
            us_results = us_sic.get_all_sic_by_name()
            
            if us_results['code'] == 200:
                successful_sources.append('us_sic')
                # Extract dependencies from response
                if 'dependencies' in us_results and 'data' in us_results['dependencies']:
                    for key, value in us_results['dependencies']['data'].items():
                        combined_dependencies['data'][key] = value
                        
                for desc, data in us_results['data']['sics'].items():
                    final_results['results'].append({
                        'description': desc,
                        'code': data['code'],
                        'source': 'us_sic',
                        'source_type': 'US SIC',
                        'additional_data': {
                            'division': data['division'],
                            'division_desc': data['division_desc'],
                            'major_group': data['major_group'],
                            'major_group_desc': data['major_group_desc'],
                            'industry_group': data['industry_group'],
                            'industry_group_desc': data['industry_group_desc']
                        }
                    })
        except Exception as e:
            self.logger.error(f"Error querying US SIC: {str(e)}")
            
        # 2. Query UK SIC
        try:
            uk_sic = UKSICQueries(db_file=self.db_file)
            uk_sic.query = query_str
            uk_results = uk_sic.get_uk_sic_by_name()
            
            if uk_results['code'] == 200:
                successful_sources.append('uk_sic')
                # Extract dependencies from response
                if 'dependencies' in uk_results and 'data' in uk_results['dependencies']:
                    for key, value in uk_results['dependencies']['data'].items():
                        combined_dependencies['data'][key] = value
                        
                for desc, data in uk_results['data']['uk_sics'].items():
                    final_results['results'].append({
                        'description': desc,
                        'code': data['code'],
                        'source': 'uk_sic',
                        'source_type': 'UK SIC',
                        'additional_data': {}
                    })
        except Exception as e:
            self.logger.error(f"Error querying UK SIC: {str(e)}")
            
        # 3. Query EU SIC (NACE)
        try:
            eu_sic = EuSICQueries(db_file=self.db_file)
            eu_sic.query = query_str
            eu_results = eu_sic.get_class_by_description()
            
            if eu_results['code'] == 200:
                successful_sources.append('eu_sic')
                # Extract dependencies from response
                if 'dependencies' in eu_results and 'data' in eu_results['dependencies']:
                    for key, value in eu_results['dependencies']['data'].items():
                        combined_dependencies['data'][key] = value
                        
                for desc, data in eu_results['data']['classes'].items():
                    final_results['results'].append({
                        'description': desc,
                        'code': data['code'],
                        'source': 'eu_sic',
                        'source_type': 'EU NACE',
                        'additional_data': {
                            'group_code': data['group_code'],
                            'division_code': data['division_code'],
                            'section_code': data['section_code']
                        }
                    })
        except Exception as e:
            self.logger.error(f"Error querying EU SIC: {str(e)}")
            
        # 4. Query International SIC (ISIC)
        try:
            isic = InternationalSICQueries(db_file=self.db_file)
            isic.query = query_str
            isic_results = isic.get_class_by_description()
            
            if isic_results['code'] == 200:
                successful_sources.append('international_sic')
                # Extract dependencies from response
                if 'dependencies' in isic_results and 'data' in isic_results['dependencies']:
                    for key, value in isic_results['dependencies']['data'].items():
                        combined_dependencies['data'][key] = value
                        
                for desc, data in isic_results['data']['classes'].items():
                    final_results['results'].append({
                        'description': desc,
                        'code': data['code'],
                        'source': 'international_sic',
                        'source_type': 'ISIC',
                        'additional_data': {
                            'group_code': data['group_code'],
                            'division_code': data['division_code'],
                            'section_code': data['section_code']
                        }
                    })
        except Exception as e:
            self.logger.error(f"Error querying International SIC: {str(e)}")
            
        # 5. Query Japan SIC
        try:
            japan_sic = JapanSICQueries(db_file=self.db_file)
            japan_sic.query = query_str
            japan_results = japan_sic.get_industry_group_by_description()
            
            if japan_results['code'] == 200:
                successful_sources.append('japan_sic')
                # Extract dependencies from response
                if 'dependencies' in japan_results and 'data' in japan_results['dependencies']:
                    for key, value in japan_results['dependencies']['data'].items():
                        combined_dependencies['data'][key] = value
                        
                for desc, data in japan_results['data']['industry_groups'].items():
                    final_results['results'].append({
                        'description': desc,
                        'code': data['code'],
                        'source': 'japan_sic',
                        'source_type': 'Japan SIC',
                        'additional_data': {
                            'group_code': data['group_code'],
                            'major_group_code': data['major_group_code'],
                            'division_code': data['division_code']
                        }
                    })
        except Exception as e:
            self.logger.error(f"Error querying Japan SIC: {str(e)}")
            
        # Update total count and sources
        final_results['total'] = len(final_results['results'])
        final_results['sources'] = {source: True for source in successful_sources}
        
        if final_results['total'] == 0:
            return {
                'code': 404,
                'message': f'No matching descriptions found across any SIC system for query [{query_str}].',
                'module': f'{my_class} -> {my_function}',
                'data': final_results,
                'dependencies': combined_dependencies
            }
        else:
            return {
                'code': 200,
                'message': f'Found {final_results["total"]} matching descriptions across {len(successful_sources)} SIC systems for query [{query_str}].',
                'module': f'{my_class} -> {my_function}',
                'data': final_results,
                'dependencies': combined_dependencies
            }