"""
Voomy Container Cost Calculator
A Streamlit application for calculating landed costs per EAN from container shipments.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import re

# Page config
st.set_page_config(
    page_title="Container Cost Calculator",
    page_icon="📦",
    layout="wide"
)

# Default categories from Voomy Motherbase
DEFAULT_CATEGORIES = {
    "Stekkerdoos": {"duty_rate": 2.7, "hs_code": "8536690000"},
    "Verdeelstekker": {"duty_rate": 2.7, "hs_code": "8536690000"},
    "Reisstekker": {"duty_rate": 2.7, "hs_code": "8536690000"},
    "Laptop Stand": {"duty_rate": 6.0, "hs_code": "7616999000"},
    "Kabel": {"duty_rate": 0.0, "hs_code": "8544429000"},
    "Powerbank": {"duty_rate": 0.0, "hs_code": "8507600000"},
    "Snellader": {"duty_rate": 0.0, "hs_code": "8504409000"},
    "Hub": {"duty_rate": 0.0, "hs_code": "8471800000"},
    "Draadloze oplader": {"duty_rate": 0.0, "hs_code": "8504409000"},
    "Other": {"duty_rate": 0.0, "hs_code": ""},
}

# Initialize session state
def init_session_state():
    if 'motherbase' not in st.session_state:
        st.session_state.motherbase = None
    if 'import_duties' not in st.session_state:
        if os.path.exists("import_duties.json"):
            with open("import_duties.json", 'r') as f:
                st.session_state.import_duties = json.load(f)
        else:
            st.session_state.import_duties = DEFAULT_CATEGORIES.copy()
    if 'supplier_orders' not in st.session_state:
        st.session_state.supplier_orders = []
    if 'container_info' not in st.session_state:
        st.session_state.container_info = {
            'container_id': '',
            'total_freight_eur': 0.0,
            'total_cbm': 0.0
        }
    if 'matched_products' not in st.session_state:
        st.session_state.matched_products = pd.DataFrame()

init_session_state()


def save_import_duties():
    """Save import duties to file"""
    with open("import_duties.json", 'w') as f:
        json.dump(st.session_state.import_duties, f, indent=2)


def load_google_sheet(url: str) -> Optional[pd.DataFrame]:
    """Load data from a public Google Sheet."""
    try:
        if 'docs.google.com/spreadsheets' in url:
            if '/d/' in url:
                sheet_id = url.split('/d/')[1].split('/')[0]
            else:
                st.error("Could not extract sheet ID from URL")
                return None
            
            if 'gid=' in url:
                gid = url.split('gid=')[1].split('&')[0].split('#')[0]
            else:
                gid = '0'
            
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
            df = pd.read_csv(csv_url)
            return df
        else:
            st.error("Please provide a Google Sheets URL")
            return None
    except Exception as e:
        st.error(f"Error loading Google Sheet: {e}")
        return None


def clean_text(text: str) -> str:
    """Clean text for matching"""
    if pd.isna(text):
        return ""
    return str(text).strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def match_product(search_text: str, motherbase: pd.DataFrame) -> Optional[Dict]:
    """Try to match a product from supplier documents to the motherbase."""
    if motherbase is None or motherbase.empty:
        return None
    
    search_clean = clean_text(search_text)
    
    if str(search_text).isdigit() and len(str(search_text)) == 13:
        matches = motherbase[motherbase['EAN'].astype(str) == str(search_text)]
        if not matches.empty:
            return matches.iloc[0].to_dict()
    
    for idx, row in motherbase.iterrows():
        ext_code = clean_text(row.get('Product code (External)', ''))
        if ext_code and (search_clean in ext_code or ext_code in search_clean):
            return row.to_dict()
    
    for idx, row in motherbase.iterrows():
        int_code = clean_text(row.get('Product code (Internal)', ''))
        if int_code and (search_clean in int_code or int_code in search_clean):
            return row.to_dict()
    
    for idx, row in motherbase.iterrows():
        simp_id = clean_text(row.get('Simplified Internal ID', ''))
        if simp_id and (search_clean in simp_id or simp_id in search_clean):
            return row.to_dict()
    
    for idx, row in motherbase.iterrows():
        title = clean_text(row.get('Title', ''))
        if title and search_clean and len(search_clean) > 5:
            if search_clean in title or title in search_clean:
                return row.to_dict()
    
    return None


def parse_ci_toporek(df: pd.DataFrame) -> pd.DataFrame:
    """Parse Toporek-style Commercial Invoice"""
    header_row = None
    for idx, row in df.iterrows():
        if any('Description' in str(val) for val in row.values if pd.notna(val)):
            header_row = idx
            break
    
    if header_row is None:
        return pd.DataFrame()
    
    data_rows = []
    for idx in range(header_row + 1, len(df)):
        row = df.iloc[idx]
        if all(pd.isna(v) or str(v).strip() == '' for v in row.values):
            continue
        if any('Total' in str(v) for v in row.values if pd.notna(v)):
            continue
        
        description = None
        qty = None
        unit_price = None
        amount = None
        
        for val in row.values:
            if pd.isna(val):
                continue
            val_str = str(val).strip()
            if val_str and not val_str.replace('.', '').replace(',', '').isdigit():
                if description is None and len(val_str) > 2:
                    description = val_str
            elif val_str:
                try:
                    num = float(val_str.replace(',', ''))
                    if num > 100000:
                        continue
                    if qty is None and num > 0 and num == int(num):
                        qty = int(num)
                    elif unit_price is None and 0 < num < 1000:
                        unit_price = num
                    elif amount is None and num > 100:
                        amount = num
                except:
                    pass
        
        if description and qty:
            data_rows.append({
                'description': description,
                'quantity': qty,
                'unit_price_usd': unit_price or (amount / qty if amount and qty else 0),
                'total_usd': amount or (unit_price * qty if unit_price and qty else 0)
            })
    
    return pd.DataFrame(data_rows)


def parse_pl_toporek(df: pd.DataFrame) -> pd.DataFrame:
    """Parse Toporek-style Packing List"""
    header_row = None
    for idx, row in df.iterrows():
        if any('Description' in str(val) for val in row.values if pd.notna(val)):
            header_row = idx
            break
    
    if header_row is None:
        return pd.DataFrame()
    
    data_rows = []
    current_product = None
    
    for idx in range(header_row + 1, len(df)):
        row = df.iloc[idx]
        if any('Total' in str(v) for v in row.values if pd.notna(v)):
            continue
        
        product_code = None
        color = None
        qty = None
        cartons = None
        cbm = None
        
        for val in row.values:
            if pd.isna(val):
                continue
            val_str = str(val).strip()
            
            if re.match(r'TP-[A-Z0-9]+', val_str, re.IGNORECASE):
                product_code = val_str
                current_product = val_str
            elif val_str in ['Black', 'White', 'Grey', 'Zwart', 'Wit']:
                color = val_str
            else:
                try:
                    num = float(val_str.replace(',', ''))
                    if 100 <= num <= 50000 and num == int(num):
                        if qty is None:
                            qty = int(num)
                    elif 1 <= num <= 500 and num == int(num):
                        if cartons is None:
                            cartons = int(num)
                    elif 0 < num < 100:
                        cbm = num
                except:
                    pass
        
        if qty and (product_code or current_product):
            data_rows.append({
                'product_code': product_code or current_product,
                'color': color or '',
                'quantity': qty,
                'cartons': cartons or 0,
                'cbm': cbm or 0
            })
    
    return pd.DataFrame(data_rows)


def calculate_landed_costs(
    supplier_orders: List[Dict],
    motherbase: pd.DataFrame,
    container_info: Dict,
    import_duties: Dict
) -> pd.DataFrame:
    """Calculate landed cost per EAN."""
    results = []
    total_container_cbm = container_info.get('total_cbm', 0) or 1
    total_freight_eur = container_info.get('total_freight_eur', 0) or 0
    
    for order in supplier_orders:
        total_order_usd = sum(
            item.get('quantity', 0) * item.get('unit_price_usd', 0)
            for item in order.get('line_items', [])
        )
        
        total_paid_eur = 0
        if order.get('payment_1'):
            p1 = order['payment_1']
            total_paid_eur += p1.get('amount_usd', 0) * p1.get('fx_rate', 1)
        if order.get('payment_2'):
            p2 = order['payment_2']
            total_paid_eur += p2.get('amount_usd', 0) * p2.get('fx_rate', 1)
        
        for item in order.get('line_items', []):
            ean = item.get('ean', '')
            category = item.get('category', 'Other')
            qty = item.get('quantity', 0)
            unit_price_usd = item.get('unit_price_usd', 0)
            item_cbm = item.get('cbm', 0)
            
            if qty <= 0:
                continue
            
            item_value_usd = qty * unit_price_usd
            value_proportion = item_value_usd / total_order_usd if total_order_usd > 0 else 0
            allocated_cost_eur = total_paid_eur * value_proportion
            product_cost_per_unit = allocated_cost_eur / qty if qty > 0 else 0
            
            cbm_proportion = item_cbm / total_container_cbm if total_container_cbm > 0 else 0
            shipping_cost_total = total_freight_eur * cbm_proportion
            shipping_cost_per_unit = shipping_cost_total / qty if qty > 0 else 0
            
            duty_config = import_duties.get(category, {})
            if isinstance(duty_config, dict):
                duty_rate = duty_config.get('duty_rate', 0) / 100
            else:
                duty_rate = float(duty_config) / 100
            import_duty_per_unit = product_cost_per_unit * duty_rate
            
            landed_cost_per_unit = product_cost_per_unit + shipping_cost_per_unit + import_duty_per_unit
            
            results.append({
                'EAN': ean,
                'Product': item.get('description', ''),
                'Supplier': order.get('supplier_name', ''),
                'Order': order.get('order_number', ''),
                'Category': category,
                'Quantity': qty,
                'CBM': item_cbm,
                'Unit Price (USD)': unit_price_usd,
                'Product Cost/Unit (EUR)': round(product_cost_per_unit, 4),
                'Shipping Cost/Unit (EUR)': round(shipping_cost_per_unit, 4),
                'Duty Rate (%)': round(duty_rate * 100, 2),
                'Import Duty/Unit (EUR)': round(import_duty_per_unit, 4),
                'Landed Cost/Unit (EUR)': round(landed_cost_per_unit, 4),
                'Total Value (EUR)': round(landed_cost_per_unit * qty, 2)
            })
    
    return pd.DataFrame(results)


def main():
    st.title("📦 Container Cost Calculator")
    st.markdown("Calculate landed costs per EAN for multi-supplier container shipments")
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "⚙️ Settings",
        "1️⃣ Product Database", 
        "2️⃣ Container Setup",
        "3️⃣ Supplier Orders",
        "4️⃣ Product Matching",
        "5️⃣ Results"
    ])
    
    # Tab 1: Settings
    with tab1:
        st.header("Import Duty Settings")
        st.markdown("Configure import duty rates per product category.")
        
        available_categories = list(st.session_state.import_duties.keys())
        if st.session_state.motherbase is not None and 'Category' in st.session_state.motherbase.columns:
            mb_categories = st.session_state.motherbase['Category'].dropna().unique().tolist()
            for cat in mb_categories:
                if cat not in available_categories:
                    available_categories.append(cat)
                    st.session_state.import_duties[cat] = {"duty_rate": 0.0, "hs_code": ""}
        
        st.subheader("Duty Rates by Category")
        
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        with col1:
            st.markdown("**Category**")
        with col2:
            st.markdown("**Duty Rate (%)**")
        with col3:
            st.markdown("**HS Code**")
        with col4:
            st.markdown("**Action**")
        
        st.markdown("---")
        
        categories_to_remove = []
        
        for cat in sorted(available_categories):
            if cat.startswith('_'):
                continue
                
            config = st.session_state.import_duties.get(cat, {})
            if isinstance(config, (int, float)):
                config = {"duty_rate": config, "hs_code": ""}
            
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            
            with col1:
                st.text(cat)
            
            with col2:
                new_rate = st.number_input(
                    "Rate",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(config.get('duty_rate', 0)),
                    step=0.1,
                    key=f"duty_rate_{cat}",
                    label_visibility="collapsed"
                )
                st.session_state.import_duties[cat] = {
                    "duty_rate": new_rate,
                    "hs_code": config.get('hs_code', '')
                }
            
            with col3:
                new_hs = st.text_input(
                    "HS Code",
                    value=config.get('hs_code', ''),
                    key=f"hs_code_{cat}",
                    label_visibility="collapsed"
                )
                st.session_state.import_duties[cat]['hs_code'] = new_hs
            
            with col4:
                if st.button("🗑️", key=f"remove_cat_{cat}"):
                    categories_to_remove.append(cat)
        
        for cat in categories_to_remove:
            del st.session_state.import_duties[cat]
            st.rerun()
        
        st.markdown("---")
        st.subheader("Add New Category")
        
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        
        with col1:
            new_cat_name = st.text_input("Category Name", key="new_cat_name")
        with col2:
            new_cat_rate = st.number_input("Duty Rate (%)", min_value=0.0, max_value=100.0, value=0.0, key="new_cat_rate")
        with col3:
            new_cat_hs = st.text_input("HS Code", key="new_cat_hs")
        with col4:
            if st.button("➕ Add"):
                if new_cat_name and new_cat_name not in st.session_state.import_duties:
                    st.session_state.import_duties[new_cat_name] = {
                        "duty_rate": new_cat_rate,
                        "hs_code": new_cat_hs
                    }
                    st.success(f"Added category: {new_cat_name}")
                    st.rerun()
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save Settings", type="primary"):
                save_import_duties()
                st.success("Settings saved!")
        
        with col2:
            if st.button("🔄 Reset to Defaults"):
                st.session_state.import_duties = DEFAULT_CATEGORIES.copy()
                st.success("Reset to defaults!")
                st.rerun()
        
        with st.expander("View/Export Configuration (JSON)"):
            st.json(st.session_state.import_duties)
    
    # Tab 2: Product Database
    with tab2:
        st.header("Upload Product Database (Motherbase)")
        
        data_source = st.radio(
            "Select data source:",
            ["Upload Excel File", "Google Sheets Link"],
            horizontal=True
        )
        
        if data_source == "Upload Excel File":
            uploaded_mb = st.file_uploader(
                "Upload ID Motherbase Excel file",
                type=['xlsx', 'xls'],
                key='motherbase_upload'
            )
            
            if uploaded_mb:
                try:
                    xl = pd.ExcelFile(uploaded_mb)
                    sheet_name = st.selectbox(
                        "Select sheet",
                        xl.sheet_names,
                        index=0 if 'ID Motherbase' not in xl.sheet_names else xl.sheet_names.index('ID Motherbase')
                    )
                    
                    df = pd.read_excel(xl, sheet_name=sheet_name)
                    
                    if 'EAN' not in df.columns:
                        df.columns = df.iloc[0]
                        df = df.iloc[1:].reset_index(drop=True)
                    
                    st.session_state.motherbase = df
                    
                    if 'Category' in df.columns:
                        categories = df['Category'].dropna().unique().tolist()
                        for cat in categories:
                            if cat not in st.session_state.import_duties:
                                st.session_state.import_duties[cat] = {"duty_rate": 0.0, "hs_code": ""}
                    
                    st.success(f"✅ Loaded {len(df)} products from {sheet_name}")
                    
                    if 'Category' in df.columns:
                        st.subheader("Products by Category")
                        cat_counts = df['Category'].value_counts()
                        st.dataframe(cat_counts, use_container_width=True)
                    
                    st.subheader("Data Preview")
                    display_cols = ['EAN', 'Product code (Internal)', 'Product code (External)', 
                                    'Category', 'Supplier', 'Title', 'CBM', 'Box amount']
                    available_cols = [c for c in display_cols if c in df.columns]
                    st.dataframe(df[available_cols].head(20), use_container_width=True)
                    
                except Exception as e:
                    st.error(f"Error loading file: {e}")
        
        else:
            st.markdown("""
            **Instructions for Google Sheets:**
            1. Open your Google Sheet
            2. Click **Share** → **Anyone with the link** → **Viewer**
            3. Copy the URL and paste below
            """)
            
            sheets_url = st.text_input(
                "Google Sheets URL",
                placeholder="https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit..."
            )
            
            if sheets_url and st.button("🔗 Load from Google Sheets"):
                with st.spinner("Loading from Google Sheets..."):
                    df = load_google_sheet(sheets_url)
                    
                    if df is not None:
                        if 'EAN' not in df.columns and len(df) > 0:
                            df.columns = df.iloc[0]
                            df = df.iloc[1:].reset_index(drop=True)
                        
                        st.session_state.motherbase = df
                        
                        if 'Category' in df.columns:
                            categories = df['Category'].dropna().unique().tolist()
                            for cat in categories:
                                if cat not in st.session_state.import_duties:
                                    st.session_state.import_duties[cat] = {"duty_rate": 0.0, "hs_code": ""}
                        
                        st.success(f"✅ Loaded {len(df)} products from Google Sheets")
                        st.dataframe(df.head(20), use_container_width=True)
    
    # Tab 3: Container Setup
    with tab3:
        st.header("Container Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.session_state.container_info['container_id'] = st.text_input(
                "Container ID / Reference",
                value=st.session_state.container_info.get('container_id', '')
            )
            
            st.session_state.container_info['total_freight_eur'] = st.number_input(
                "Total Freight Cost (EUR)",
                min_value=0.0,
                value=float(st.session_state.container_info.get('total_freight_eur', 0)),
                step=100.0
            )
        
        with col2:
            st.session_state.container_info['total_cbm'] = st.number_input(
                "Total Container CBM",
                min_value=0.0,
                value=float(st.session_state.container_info.get('total_cbm', 0)),
                step=0.1
            )
            
            st.session_state.container_info['arrival_date'] = st.date_input(
                "Expected Arrival Date",
                value=datetime.now()
            )
        
        if st.session_state.supplier_orders:
            st.markdown("---")
            st.subheader("Container Summary")
            
            total_items = sum(len(o.get('line_items', [])) for o in st.session_state.supplier_orders)
            total_units = sum(
                item.get('quantity', 0) 
                for o in st.session_state.supplier_orders 
                for item in o.get('line_items', [])
            )
            total_cbm = sum(
                item.get('cbm', 0)
                for o in st.session_state.supplier_orders
                for item in o.get('line_items', [])
            )
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Suppliers", len(st.session_state.supplier_orders))
            col2.metric("Line Items", total_items)
            col3.metric("Total Units", f"{total_units:,}")
            col4.metric("Calculated CBM", f"{total_cbm:.2f}")
    
    # Tab 4: Supplier Orders
    with tab4:
        st.header("Supplier Orders")
        
        with st.expander("➕ Add New Supplier Order", expanded=True):
            supplier_col1, supplier_col2 = st.columns(2)
            
            with supplier_col1:
                supplier_name = st.text_input("Supplier Name", key="new_supplier_name")
                order_number = st.text_input("Order Number", key="new_order_number")
            
            with supplier_col2:
                st.markdown("**Payment 1 (Deposit)**")
                p1_amount = st.number_input("Amount (USD)", min_value=0.0, key="p1_amount")
                p1_fx = st.number_input("FX Rate (USD→EUR)", min_value=0.0, value=0.92, key="p1_fx", step=0.01)
                p1_date = st.date_input("Date", key="p1_date")
            
            st.markdown("---")
            
            payment_col1, payment_col2 = st.columns(2)
            
            with payment_col1:
                st.markdown("**Payment 2 (Balance)**")
                p2_amount = st.number_input("Amount (USD)", min_value=0.0, key="p2_amount")
                p2_fx = st.number_input("FX Rate (USD→EUR)", min_value=0.0, value=0.92, key="p2_fx", step=0.01)
                p2_date = st.date_input("Date", key="p2_date")
            
            with payment_col2:
                st.markdown("**Upload Documents**")
                ci_file = st.file_uploader("Commercial Invoice (CI)", type=['xlsx', 'xls', 'pdf'], key="ci_upload")
                pl_file = st.file_uploader("Packing List (PL)", type=['xlsx', 'xls', 'pdf'], key="pl_upload")
            
            if ci_file or pl_file:
                st.markdown("### Extracted Line Items")
                
                if ci_file and ci_file.name.endswith(('.xlsx', '.xls')):
                    try:
                        ci_df = pd.read_excel(ci_file)
                        parsed_ci = parse_ci_toporek(ci_df)
                        if not parsed_ci.empty:
                            st.write("**From CI:**")
                            st.dataframe(parsed_ci)
                    except Exception as e:
                        st.warning(f"Could not auto-parse CI: {e}")
                
                if pl_file and pl_file.name.endswith(('.xlsx', '.xls')):
                    try:
                        pl_df = pd.read_excel(pl_file)
                        parsed_pl = parse_pl_toporek(pl_df)
                        if not parsed_pl.empty:
                            st.write("**From PL:**")
                            st.dataframe(parsed_pl)
                    except Exception as e:
                        st.warning(f"Could not auto-parse PL: {e}")
            
            st.markdown("### Manual Line Item Entry")
            st.markdown("Enter items: `Product Code | Quantity | Unit Price (USD) | CBM`")
            
            manual_items = st.text_area(
                "Line items (one per line)",
                height=150,
                placeholder="TP-MA4U4E 2M Black | 1800 | 7.23 | 4.25\nTP-WJ4U4E Black | 1980 | 6.25 | 2.31",
                key="manual_items"
            )
            
            if st.button("Add Supplier Order", type="primary"):
                if supplier_name and order_number:
                    parsed_items = []
                    for line in manual_items.strip().split('\n'):
                        if '|' in line:
                            parts = [p.strip() for p in line.split('|')]
                            if len(parts) >= 3:
                                parsed_items.append({
                                    'product_code': parts[0],
                                    'description': parts[0],
                                    'quantity': int(float(parts[1])),
                                    'unit_price_usd': float(parts[2]),
                                    'cbm': float(parts[3]) if len(parts) > 3 else 0
                                })
                    
                    new_order = {
                        'supplier_name': supplier_name,
                        'order_number': order_number,
                        'payment_1': {
                            'amount_usd': p1_amount,
                            'fx_rate': p1_fx,
                            'date': str(p1_date)
                        } if p1_amount > 0 else None,
                        'payment_2': {
                            'amount_usd': p2_amount,
                            'fx_rate': p2_fx,
                            'date': str(p2_date)
                        } if p2_amount > 0 else None,
                        'line_items': parsed_items
                    }
                    
                    st.session_state.supplier_orders.append(new_order)
                    st.success(f"Added order {order_number} from {supplier_name}")
                    st.rerun()
                else:
                    st.error("Please enter supplier name and order number")
        
        st.markdown("---")
        st.subheader("Current Orders")
        
        for i, order in enumerate(st.session_state.supplier_orders):
            with st.expander(f"📦 {order['supplier_name']} - Order #{order['order_number']}"):
                total_qty = sum(item.get('quantity', 0) for item in order.get('line_items', []))
                total_value = sum(
                    item.get('quantity', 0) * item.get('unit_price_usd', 0) 
                    for item in order.get('line_items', [])
                )
                
                st.write(f"**Items:** {len(order.get('line_items', []))} | **Total Qty:** {total_qty:,} | **Total Value:** ${total_value:,.2f}")
                
                if order.get('payment_1'):
                    p1 = order['payment_1']
                    st.write(f"**Payment 1:** ${p1['amount_usd']:,.2f} @ {p1['fx_rate']} = €{p1['amount_usd'] * p1['fx_rate']:,.2f}")
                
                if order.get('payment_2'):
                    p2 = order['payment_2']
                    st.write(f"**Payment 2:** ${p2['amount_usd']:,.2f} @ {p2['fx_rate']} = €{p2['amount_usd'] * p2['fx_rate']:,.2f}")
                
                if order.get('line_items'):
                    st.dataframe(pd.DataFrame(order['line_items']), use_container_width=True)
                
                if st.button(f"🗑️ Remove Order", key=f"remove_{i}"):
                    st.session_state.supplier_orders.pop(i)
                    st.rerun()
    
    # Tab 5: Product Matching
    with tab5:
        st.header("Product Matching")
        
        if st.session_state.motherbase is None:
            st.warning("⚠️ Please upload the Motherbase first in Tab 2")
        elif not st.session_state.supplier_orders:
            st.warning("⚠️ Please add supplier orders first in Tab 4")
        else:
            all_items = []
            for order in st.session_state.supplier_orders:
                for item in order.get('line_items', []):
                    item_copy = item.copy()
                    item_copy['supplier'] = order['supplier_name']
                    item_copy['order'] = order['order_number']
                    all_items.append(item_copy)
            
            if not all_items:
                st.info("No line items to match")
            else:
                matched = []
                unmatched = []
                
                for item in all_items:
                    search_text = item.get('product_code', item.get('description', ''))
                    match = match_product(search_text, st.session_state.motherbase)
                    
                    if match:
                        item['ean'] = match.get('EAN', '')
                        item['matched_title'] = match.get('Title', '')
                        item['category'] = match.get('Category', 'Other')
                        matched.append(item)
                    else:
                        unmatched.append(item)
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Items", len(all_items))
                col2.metric("Matched", len(matched), delta=f"{100*len(matched)/len(all_items):.1f}%")
                col3.metric("Unmatched", len(unmatched))
                
                st.subheader("✅ Matched Products")
                if matched:
                    st.dataframe(pd.DataFrame(matched), use_container_width=True)
                
                st.subheader("❌ Unmatched Products")
                if unmatched:
                    for i, item in enumerate(unmatched):
                        col1, col2 = st.columns([2, 1])
                        
                        with col1:
                            st.write(f"**{item.get('product_code', 'Unknown')}** - Qty: {item.get('quantity', 0)}")
                        
                        with col2:
                            ean_options = [''] + st.session_state.motherbase['EAN'].astype(str).tolist()
                            selected_ean = st.selectbox("Select EAN", ean_options, key=f"manual_ean_{i}")
                            
                            if selected_ean:
                                mb_row = st.session_state.motherbase[
                                    st.session_state.motherbase['EAN'].astype(str) == selected_ean
                                ].iloc[0]
                                item['ean'] = selected_ean
                                item['category'] = mb_row.get('Category', 'Other')
                                matched.append(item)
                
                for order in st.session_state.supplier_orders:
                    for item in order.get('line_items', []):
                        for m in matched:
                            if item.get('product_code') == m.get('product_code'):
                                item['ean'] = m.get('ean', '')
                                item['category'] = m.get('category', 'Other')
    
    # Tab 6: Results
    with tab6:
        st.header("Landed Cost Results")
        
        if not st.session_state.supplier_orders:
            st.warning("⚠️ Please add supplier orders first")
        elif st.session_state.container_info.get('total_freight_eur', 0) == 0:
            st.warning("⚠️ Please enter container freight cost in Tab 3")
        else:
            if st.session_state.container_info.get('total_cbm', 0) == 0:
                total_cbm = sum(
                    item.get('cbm', 0)
                    for order in st.session_state.supplier_orders
                    for item in order.get('line_items', [])
                )
                st.session_state.container_info['total_cbm'] = total_cbm
            
            results_df = calculate_landed_costs(
                st.session_state.supplier_orders,
                st.session_state.motherbase,
                st.session_state.container_info,
                st.session_state.import_duties
            )
            
            if not results_df.empty:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Products", len(results_df))
                col2.metric("Total Units", f"{results_df['Quantity'].sum():,}")
                col3.metric("Total Value", f"€{results_df['Total Value (EUR)'].sum():,.2f}")
                col4.metric("Avg Landed Cost", f"€{results_df['Landed Cost/Unit (EUR)'].mean():.2f}")
                
                st.subheader("Cost Breakdown by EAN")
                st.dataframe(results_df, use_container_width=True)
                
                st.subheader("Summary by Category")
                category_summary = results_df.groupby('Category').agg({
                    'Quantity': 'sum',
                    'Total Value (EUR)': 'sum',
                    'Duty Rate (%)': 'first'
                }).round(2)
                st.dataframe(category_summary, use_container_width=True)
                
                export_buffer = pd.io.common.BytesIO()
                with pd.ExcelWriter(export_buffer, engine='openpyxl') as writer:
                    results_df.to_excel(writer, sheet_name='Landed Costs', index=False)
                    
                    duties_df = pd.DataFrame([
                        {'Category': k, 'Duty Rate (%)': v.get('duty_rate', 0) if isinstance(v, dict) else v}
                        for k, v in st.session_state.import_duties.items()
                        if not k.startswith('_')
                    ])
                    duties_df.to_excel(writer, sheet_name='Import Duties', index=False)
                
                export_buffer.seek(0)
                
                st.download_button(
                    label="📥 Download Results (Excel)",
                    data=export_buffer,
                    file_name=f"landed_costs_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )


if __name__ == "__main__":
    main()
