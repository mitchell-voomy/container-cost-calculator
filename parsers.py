"""
Parsers for different supplier CI and PL formats.
Add new parsers here when encountering new supplier document formats.
"""

import pandas as pd
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class LineItem:
    product_code: str
    description: str
    quantity: int
    unit_price_usd: float
    cbm: float
    color: str = ""
    cartons: int = 0
    gross_weight: float = 0
    net_weight: float = 0


def clean_number(val) -> Optional[float]:
    """Extract numeric value from various formats"""
    if pd.isna(val):
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        val_str = str(val).strip().replace(',', '').replace('$', '').replace('€', '')
        return float(val_str)
    except:
        return None


def detect_supplier_format(df: pd.DataFrame) -> str:
    """Detect which supplier format the document uses"""
    text = df.to_string().lower()
    
    if 'ainisi' in text or 'toporek' in text.lower():
        return 'toporek'
    elif 'ouli' in text or 'ouliyo' in text:
        return 'ouli'
    elif 'youji' in text or 'guangzhou' in text:
        return 'youji'
    else:
        return 'generic'


class ToporekParser:
    """Parser for Toporek/Ainisi documents"""
    
    @staticmethod
    def parse_ci(df: pd.DataFrame) -> List[LineItem]:
        """Parse Toporek Commercial Invoice"""
        items = []
        
        # Find header row containing "Description"
        header_row = None
        for idx, row in df.iterrows():
            row_text = ' '.join(str(v) for v in row.values if pd.notna(v))
            if 'description' in row_text.lower() and 'qty' in row_text.lower():
                header_row = idx
                break
        
        if header_row is None:
            return items
        
        # Map column names
        headers = df.iloc[header_row].values
        col_map = {}
        for i, h in enumerate(headers):
            h_str = str(h).lower() if pd.notna(h) else ''
            if 'description' in h_str:
                col_map['description'] = i
            elif 'qty' in h_str:
                col_map['qty'] = i
            elif 'unit' in h_str and 'price' in h_str:
                col_map['unit_price'] = i
            elif 'amount' in h_str:
                col_map['amount'] = i
            elif 'g.w' in h_str or 'gross' in h_str:
                col_map['gw'] = i
        
        # Parse data rows
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx].values
            
            # Skip total row
            row_text = ' '.join(str(v) for v in row if pd.notna(v))
            if 'total' in row_text.lower():
                continue
            
            # Extract values
            desc = row[col_map.get('description', 1)] if col_map.get('description') is not None else None
            qty = clean_number(row[col_map.get('qty', 3)]) if col_map.get('qty') is not None else None
            unit_price = clean_number(row[col_map.get('unit_price', 5)]) if col_map.get('unit_price') is not None else None
            amount = clean_number(row[col_map.get('amount', 6)]) if col_map.get('amount') is not None else None
            
            if desc and qty and qty > 0:
                # If no unit price, calculate from amount
                if not unit_price and amount:
                    unit_price = amount / qty
                
                items.append(LineItem(
                    product_code=str(desc).strip(),
                    description=str(desc).strip(),
                    quantity=int(qty),
                    unit_price_usd=unit_price or 0,
                    cbm=0  # CBM comes from PL
                ))
        
        return items
    
    @staticmethod
    def parse_pl(df: pd.DataFrame) -> List[LineItem]:
        """Parse Toporek Packing List"""
        items = []
        
        # Find header row
        header_row = None
        for idx, row in df.iterrows():
            row_text = ' '.join(str(v) for v in row.values if pd.notna(v))
            if 'description' in row_text.lower() or 'carton' in row_text.lower():
                header_row = idx
                break
        
        if header_row is None:
            return items
        
        current_product = None
        
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx].values
            row_text = ' '.join(str(v) for v in row if pd.notna(v))
            
            if 'total' in row_text.lower():
                continue
            
            # Extract product code (TP-XXX pattern)
            product_match = re.search(r'TP-[A-Z0-9-]+', row_text, re.IGNORECASE)
            if product_match:
                current_product = product_match.group()
            
            # Extract color
            color = ''
            for c in ['Black', 'White', 'Grey', 'Zwart', 'Wit', 'Grijs']:
                if c.lower() in row_text.lower():
                    color = c
                    break
            
            # Extract numbers
            numbers = []
            for val in row:
                num = clean_number(val)
                if num is not None and num > 0:
                    numbers.append(num)
            
            # Heuristic: quantity is usually largest whole number < 10000
            # Cartons is smaller whole number
            # CBM is decimal < 100
            qty = None
            cartons = None
            cbm = None
            
            for num in sorted(numbers, reverse=True):
                if num == int(num):  # Whole number
                    if qty is None and 10 < num < 50000:
                        qty = int(num)
                    elif cartons is None and 1 < num < 1000:
                        cartons = int(num)
                else:  # Decimal
                    if cbm is None and 0 < num < 100:
                        cbm = num
            
            if current_product and qty:
                items.append(LineItem(
                    product_code=current_product,
                    description=f"{current_product} {color}".strip(),
                    quantity=qty,
                    unit_price_usd=0,  # Price comes from CI
                    cbm=cbm or 0,
                    color=color,
                    cartons=cartons or 0
                ))
        
        return items


class OuliParser:
    """Parser for Ouli/Ouliyo documents"""
    
    @staticmethod
    def parse_ci(df: pd.DataFrame) -> List[LineItem]:
        """Parse Ouli Commercial Invoice"""
        items = []
        
        # Find header row
        header_row = None
        for idx, row in df.iterrows():
            row_text = ' '.join(str(v) for v in row.values if pd.notna(v))
            if 'item' in row_text.lower() and ('qty' in row_text.lower() or 'quantity' in row_text.lower()):
                header_row = idx
                break
        
        if header_row is None:
            return items
        
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx].values
            row_text = ' '.join(str(v) for v in row if pd.notna(v))
            
            if 'total' in row_text.lower():
                continue
            
            # Extract OL-XXX product code
            product_match = re.search(r'OL-[A-Z0-9-]+', row_text, re.IGNORECASE)
            voomy_match = re.search(r'V[YX]\d+', row_text, re.IGNORECASE)
            
            product_code = product_match.group() if product_match else (voomy_match.group() if voomy_match else None)
            
            if not product_code:
                continue
            
            # Extract numbers
            numbers = []
            for val in row:
                num = clean_number(val)
                if num is not None and num > 0:
                    numbers.append(num)
            
            # Quantity is whole number, price is small decimal
            qty = None
            unit_price = None
            
            for num in numbers:
                if num == int(num) and 1 < num < 50000:
                    if qty is None or num > qty:
                        qty = int(num)
                elif 0 < num < 100:
                    unit_price = num
            
            if product_code and qty:
                items.append(LineItem(
                    product_code=product_code,
                    description=product_code,
                    quantity=qty,
                    unit_price_usd=unit_price or 0,
                    cbm=0
                ))
        
        return items
    
    @staticmethod
    def parse_pl(df: pd.DataFrame) -> List[LineItem]:
        """Parse Ouli Packing List"""
        items = []
        
        # Similar logic to CI but extract CBM
        header_row = None
        for idx, row in df.iterrows():
            row_text = ' '.join(str(v) for v in row.values if pd.notna(v))
            if 'item' in row_text.lower() or 'model' in row_text.lower():
                header_row = idx
                break
        
        if header_row is None:
            return items
        
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx].values
            row_text = ' '.join(str(v) for v in row if pd.notna(v))
            
            if 'total' in row_text.lower():
                continue
            
            # Extract product codes
            product_match = re.search(r'(OL-[A-Z0-9-]+|Y\d{3}/OL-[A-Z0-9]+)', row_text, re.IGNORECASE)
            
            if not product_match:
                continue
            
            product_code = product_match.group()
            
            # Extract numbers
            numbers = []
            for val in row:
                num = clean_number(val)
                if num is not None and num > 0:
                    numbers.append(num)
            
            qty = None
            cbm = None
            cartons = None
            
            for num in sorted(numbers, reverse=True):
                if num == int(num):
                    if qty is None and 10 < num < 50000:
                        qty = int(num)
                    elif cartons is None and 1 < num < 500:
                        cartons = int(num)
                else:
                    if cbm is None and 0 < num < 50:
                        cbm = num
            
            if product_code and qty:
                items.append(LineItem(
                    product_code=product_code,
                    description=product_code,
                    quantity=qty,
                    unit_price_usd=0,
                    cbm=cbm or 0,
                    cartons=cartons or 0
                ))
        
        return items


class GenericParser:
    """Generic parser for unknown formats"""
    
    @staticmethod
    def parse(df: pd.DataFrame) -> List[LineItem]:
        """Try to extract line items from any tabular format"""
        items = []
        
        # Look for rows with product-like patterns
        for idx, row in df.iterrows():
            row_text = ' '.join(str(v) for v in row.values if pd.notna(v))
            
            # Skip obvious header/footer rows
            if any(x in row_text.lower() for x in ['total', 'invoice', 'date', 'address', 'bank']):
                continue
            
            # Look for product code patterns
            product_patterns = [
                r'TP-[A-Z0-9-]+',
                r'OL-[A-Z0-9-]+',
                r'V[XSTC]\d{4}',
                r'[A-Z]{2,4}-[A-Z0-9]{4,}',
            ]
            
            product_code = None
            for pattern in product_patterns:
                match = re.search(pattern, row_text, re.IGNORECASE)
                if match:
                    product_code = match.group()
                    break
            
            if not product_code:
                continue
            
            # Extract numbers
            numbers = []
            for val in row.values:
                num = clean_number(val)
                if num is not None and num > 0:
                    numbers.append(num)
            
            if len(numbers) >= 1:
                # Assume largest whole number is quantity
                qty = int(max(n for n in numbers if n == int(n) and n < 50000) or 0)
                
                if qty > 0:
                    items.append(LineItem(
                        product_code=product_code,
                        description=product_code,
                        quantity=qty,
                        unit_price_usd=0,
                        cbm=0
                    ))
        
        return items


def parse_document(df: pd.DataFrame, doc_type: str = 'ci') -> List[LineItem]:
    """
    Parse a CI or PL document and extract line items.
    
    Args:
        df: DataFrame from the uploaded file
        doc_type: 'ci' for Commercial Invoice, 'pl' for Packing List
    
    Returns:
        List of LineItem objects
    """
    supplier_format = detect_supplier_format(df)
    
    if supplier_format == 'toporek':
        if doc_type == 'ci':
            return ToporekParser.parse_ci(df)
        else:
            return ToporekParser.parse_pl(df)
    
    elif supplier_format == 'ouli':
        if doc_type == 'ci':
            return OuliParser.parse_ci(df)
        else:
            return OuliParser.parse_pl(df)
    
    else:
        return GenericParser.parse(df)


def merge_ci_pl(ci_items: List[LineItem], pl_items: List[LineItem]) -> List[LineItem]:
    """
    Merge CI and PL data to get complete line items with both price and CBM.
    """
    merged = []
    
    # Create lookup from PL items
    pl_lookup = {}
    for item in pl_items:
        key = clean_code(item.product_code)
        if key not in pl_lookup:
            pl_lookup[key] = []
        pl_lookup[key].append(item)
    
    for ci_item in ci_items:
        key = clean_code(ci_item.product_code)
        
        # Find matching PL item
        if key in pl_lookup:
            pl_matches = pl_lookup[key]
            # Sum CBM from all matching PL rows
            total_cbm = sum(p.cbm for p in pl_matches)
            ci_item.cbm = total_cbm
        
        merged.append(ci_item)
    
    return merged


def clean_code(code: str) -> str:
    """Normalize product code for matching"""
    return re.sub(r'[^A-Z0-9]', '', str(code).upper())
