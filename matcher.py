"""
Product matching engine for linking supplier products to Motherbase EANs.
Supports multiple matching strategies with confidence scoring.
"""

import pandas as pd
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class MatchResult:
    ean: str
    title: str
    category: str
    supplier: str
    internal_code: str
    external_code: str
    cbm: float
    box_amount: int
    confidence: float  # 0-1, how confident we are in the match
    match_method: str  # How the match was found


def normalize(text: str) -> str:
    """Normalize text for matching"""
    if pd.isna(text):
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(text).upper())


def similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class ProductMatcher:
    """
    Match products from supplier documents to Motherbase.
    
    Matching strategies (in order of confidence):
    1. Exact EAN match (confidence: 1.0)
    2. Exact external code match (confidence: 0.95)
    3. Exact internal code match (confidence: 0.95)
    4. Partial external code match (confidence: 0.8)
    5. Simplified ID match (confidence: 0.75)
    6. Title similarity match (confidence: 0.5-0.7)
    """
    
    def __init__(self, motherbase: pd.DataFrame):
        """
        Initialize with Motherbase DataFrame.
        
        Expected columns:
        - EAN
        - Product code (Internal)
        - Product code (External)
        - Simplified Internal ID
        - Title
        - Category
        - Supplier
        - CBM
        - Box amount
        """
        self.motherbase = motherbase
        self._build_indices()
    
    def _build_indices(self):
        """Build lookup indices for fast matching"""
        self.ean_index = {}
        self.external_code_index = {}
        self.internal_code_index = {}
        self.simplified_id_index = {}
        
        for idx, row in self.motherbase.iterrows():
            # EAN index
            ean = str(row.get('EAN', '')).strip()
            if ean and ean != 'nan':
                self.ean_index[ean] = idx
            
            # External code index (supplier code)
            ext_code = normalize(row.get('Product code (External)', ''))
            if ext_code:
                self.external_code_index[ext_code] = idx
            
            # Internal code index
            int_code = normalize(row.get('Product code (Internal)', ''))
            if int_code:
                self.internal_code_index[int_code] = idx
            
            # Simplified ID index
            simp_id = normalize(row.get('Simplified Internal ID', ''))
            if simp_id:
                self.simplified_id_index[simp_id] = idx
    
    def _get_result(self, idx: int, confidence: float, method: str) -> MatchResult:
        """Create MatchResult from Motherbase row index"""
        row = self.motherbase.iloc[idx]
        return MatchResult(
            ean=str(row.get('EAN', '')),
            title=str(row.get('Title', '')),
            category=str(row.get('Category', '')),
            supplier=str(row.get('Supplier', '')),
            internal_code=str(row.get('Product code (Internal)', '')),
            external_code=str(row.get('Product code (External)', '')),
            cbm=float(row.get('CBM', 0) or 0),
            box_amount=int(row.get('Box amount', 0) or 0),
            confidence=confidence,
            match_method=method
        )
    
    def match(self, search_text: str, supplier_hint: str = None) -> Optional[MatchResult]:
        """
        Find the best match for a product from supplier documents.
        
        Args:
            search_text: Product code, name, or EAN from supplier document
            supplier_hint: Optional supplier name to narrow matches
        
        Returns:
            MatchResult if found, None otherwise
        """
        if not search_text or pd.isna(search_text):
            return None
        
        search_text = str(search_text).strip()
        search_normalized = normalize(search_text)
        
        # Try expanded search terms (product name mappings)
        search_terms = expand_search_text(search_text)
        for term in search_terms:
            term_normalized = normalize(term)
            
            # Check internal code index with mapped names
            if term_normalized in self.internal_code_index:
                return self._get_result(self.internal_code_index[term_normalized], 0.9, 'mapped_internal_code')
        
        # Strategy 1: Exact EAN match
        if search_text.isdigit() and len(search_text) == 13:
            if search_text in self.ean_index:
                return self._get_result(self.ean_index[search_text], 1.0, 'exact_ean')
        
        # Strategy 2: Exact external code match
        if search_normalized in self.external_code_index:
            return self._get_result(self.external_code_index[search_normalized], 0.95, 'exact_external_code')
        
        # Strategy 3: Exact internal code match
        if search_normalized in self.internal_code_index:
            return self._get_result(self.internal_code_index[search_normalized], 0.95, 'exact_internal_code')
        
        # Strategy 4: Partial external code match
        for ext_code, idx in self.external_code_index.items():
            if search_normalized in ext_code or ext_code in search_normalized:
                # Check if supplier matches (if hint provided)
                if supplier_hint:
                    row_supplier = str(self.motherbase.iloc[idx].get('Supplier', '')).lower()
                    if supplier_hint.lower() not in row_supplier:
                        continue
                return self._get_result(idx, 0.8, 'partial_external_code')
        
        # Strategy 5: Simplified ID match
        for simp_id, idx in self.simplified_id_index.items():
            if similarity(search_normalized, simp_id) > 0.8:
                return self._get_result(idx, 0.75, 'simplified_id')
            # Also check if search text contains the simplified ID
            if simp_id in search_normalized:
                return self._get_result(idx, 0.7, 'partial_simplified_id')
        
        # Strategy 6: Title similarity match (last resort)
        best_match = None
        best_score = 0.5  # Minimum threshold
        
        for idx, row in self.motherbase.iterrows():
            title = str(row.get('Title', ''))
            score = similarity(search_text, title)
            
            # Boost score if supplier matches
            if supplier_hint:
                row_supplier = str(row.get('Supplier', '')).lower()
                if supplier_hint.lower() in row_supplier:
                    score += 0.1
            
            if score > best_score:
                best_score = score
                best_match = idx
        
        if best_match is not None:
            return self._get_result(best_match, min(best_score, 0.7), 'title_similarity')
        
        return None
    
    def match_batch(self, items: List[Dict], supplier_hint: str = None) -> List[Tuple[Dict, Optional[MatchResult]]]:
        """
        Match a batch of items.
        
        Args:
            items: List of dicts with at least 'product_code' or 'description' key
            supplier_hint: Optional supplier name
        
        Returns:
            List of (item, match_result) tuples
        """
        results = []
        
        for item in items:
            # Try product_code first, then description
            search_text = item.get('product_code') or item.get('description', '')
            match = self.match(search_text, supplier_hint)
            results.append((item, match))
        
        return results
    
    def get_match_summary(self, results: List[Tuple[Dict, Optional[MatchResult]]]) -> Dict:
        """Get summary statistics for a batch of matches"""
        total = len(results)
        matched = sum(1 for _, m in results if m is not None)
        high_confidence = sum(1 for _, m in results if m and m.confidence >= 0.8)
        
        by_method = {}
        for _, m in results:
            if m:
                by_method[m.match_method] = by_method.get(m.match_method, 0) + 1
        
        return {
            'total': total,
            'matched': matched,
            'unmatched': total - matched,
            'match_rate': matched / total if total > 0 else 0,
            'high_confidence_rate': high_confidence / total if total > 0 else 0,
            'by_method': by_method
        }


# Common product name mappings for Voomy products
PRODUCT_NAME_MAPPINGS = {
    # Toporek simplified names to internal codes
    'power s7': 'VS0711',
    'power s8': 'VS0811',
    'power s9': 'VS0911',
    'power s12': 'VS1211',
    'power s12c': 'VS12C',
    'power s65': 'VS6511',
    'power s100': 'VS10011',
    'power cube s5': 'VS0511',
    'power cube s6': 'VS0611',
    'power cube s6-w': 'VS0621',
    'power cube s6-5m': 'VS0651',
    'power cube s6-3m': 'VS0631',
    'split x2': 'VX0212',
    'split x3': 'VX0312',
    'split x4': 'VX0412',
    'split x7': 'VX0712',
    'power s2': 'VS0211',
    'office t3': 'VT0311',
    'travel y711': 'VY711',
    'travel y712': 'VY712',
    'travel y713': 'VY713',
    'travel y714': 'VY714',
}


def expand_search_text(text: str) -> List[str]:
    """
    Expand search text to include common variations.
    Returns list of possible search terms.
    """
    results = [text]
    text_lower = text.lower().strip()
    
    # Check product name mappings
    for name, code in PRODUCT_NAME_MAPPINGS.items():
        if name in text_lower:
            results.append(code)
    
    # Extract color variations
    colors = {
        'zwart': 'black',
        'wit': 'white',
        'grijs': 'grey',
        'zilver': 'silver',
    }
    
    for nl, en in colors.items():
        if nl in text_lower:
            results.append(text_lower.replace(nl, en))
        if en in text_lower:
            results.append(text_lower.replace(en, nl))
    
    return results
