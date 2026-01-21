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
from typing import Dict, List, Optional
import re

st.set_page_config(page_title="Container Cost Calculator", page_icon="📦", layout="wide")

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
        st.session_state.container_info = {'container_id': '', 'total_freight_eur': 0.0, 'total_cbm': 0.0}
    if 'matched_products' not in st.session_state:
        st.session_state.matched_products = pd.DataFrame()

init_session_state()

def save_import_duties():
    with open("import_duties.json", 'w') as f:
        json.dump(st.session_state.import_duties, f, indent=2)

def load_google_sheet(url: str) -> Optional[pd.DataFrame]:
    try:
        if 'docs.google.com/spreadsheets' in url:
            sheet_id = url.split('/d/')[1].split('/')[0]
            gid = url.split('gid=')[1].split('&')[0].split('#')[0] if 'gid=' in url else '0'
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
            return pd.read_csv(csv_url)
        return None
    except Exception as e:
        st.error(f"Error loading Google Sheet: {e}")
        return None

def clean_text(text: str) -> str:
    if pd.isna(text):
        return ""
    return str(text).strip().lower().replace(" ", "").replace("-", "").replace("_", "")

def match_product(search_text: str, motherbase: pd.DataFrame) -> Optional[Dict]:
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
    
    return None

def calculate_landed_costs(supplier_orders, motherbase, container_info, import_duties):
    results = []
    total_container_cbm = container_info.get('total_cbm', 0) or 1
    total_freight_eur = container_info.get('total_freight_eur', 0) or 0
    
    for order in supplier_orders:
        total_order_usd = sum(item.get('quantity', 0) * item.get('unit_price_usd', 0) for item in order.get('line_items', []))
        
        total_paid_eur = 0
        if order.get('payment_1'):
            total_paid_eur += order['payment_1'].get('amount_eur', 0)
        if order.get('payment_2'):
            total_paid_eur += order['payment_2'].get('amount_eur', 0)
        
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
            shipping_cost_per_unit = (total_freight_eur * cbm_proportion) / qty if qty > 0 else 0
            
            duty_config = import_duties.get(category, {})
            duty_rate = (duty_config.get('duty_rate', 0) if isinstance(duty_config, dict) else float(duty_config)) / 100
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
        "⚙️ Settings", "1️⃣ Product Database", "2️⃣ Container Setup",
        "3️⃣ Supplier Orders", "4️⃣ Product Matching", "5️⃣ Results"
    ])
    
    # Tab 1: Settings
    with tab1:
        st.header("Import Duty Settings")
        
        available_categories = list(st.session_state.import_duties.keys())
        if st.session_state.motherbase is not None and 'Category' in st.session_state.motherbase.columns:
            for cat in st.session_state.motherbase['Category'].dropna().unique():
                if cat not in available_categories:
                    available_categories.append(cat)
                    st.session_state.import_duties[cat] = {"duty_rate": 0.0, "hs_code": ""}
        
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        col1.markdown("**Category**")
        col2.markdown("**Duty Rate (%)**")
        col3.markdown("**HS Code**")
        col4.markdown("**Action**")
        st.markdown("---")
        
        categories_to_remove = []
        for cat in sorted(available_categories):
            if cat.startswith('_'):
                continue
            config = st.session_state.import_duties.get(cat, {})
            if isinstance(config, (int, float)):
                config = {"duty_rate": config, "hs_code": ""}
            
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            col1.text(cat)
            new_rate = col2.number_input("Rate", min_value=0.0, max_value=100.0, value=float(config.get('duty_rate', 0)), step=0.1, key=f"duty_rate_{cat}", label_visibility="collapsed")
            new_hs = col3.text_input("HS", value=config.get('hs_code', ''), key=f"hs_code_{cat}", label_visibility="collapsed")
            st.session_state.import_duties[cat] = {"duty_rate": new_rate, "hs_code": new_hs}
            if col4.button("🗑️", key=f"remove_cat_{cat}"):
                categories_to_remove.append(cat)
        
        for cat in categories_to_remove:
            del st.session_state.import_duties[cat]
            st.rerun()
        
        st.markdown("---")
        st.subheader("Add New Category")
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        new_cat_name = col1.text_input("Category Name", key="new_cat_name")
        new_cat_rate = col2.number_input("Rate (%)", min_value=0.0, max_value=100.0, value=0.0, key="new_cat_rate")
        new_cat_hs = col3.text_input("HS Code", key="new_cat_hs")
        if col4.button("➕"):
            if new_cat_name and new_cat_name not in st.session_state.import_duties:
                st.session_state.import_duties[new_cat_name] = {"duty_rate": new_cat_rate, "hs_code": new_cat_hs}
                st.rerun()
        
        st.markdown("---")
        col1, col2 = st.columns(2)
        if col1.button("💾 Save Settings", type="primary"):
            save_import_duties()
            st.success("Settings saved!")
        if col2.button("🔄 Reset to Defaults"):
            st.session_state.import_duties = DEFAULT_CATEGORIES.copy()
            st.rerun()
    
    # Tab 2: Product Database
    with tab2:
        st.header("Upload Product Database (Motherbase)")
        data_source = st.radio("Select data source:", ["Upload Excel File", "Google Sheets Link"], horizontal=True)
        
        if data_source == "Upload Excel File":
            uploaded_mb = st.file_uploader("Upload ID Motherbase Excel file", type=['xlsx', 'xls'])
            if uploaded_mb:
                try:
                    xl = pd.ExcelFile(uploaded_mb)
                    sheet_name = st.selectbox("Select sheet", xl.sheet_names, index=xl.sheet_names.index('ID Motherbase') if 'ID Motherbase' in xl.sheet_names else 0)
                    df = pd.read_excel(xl, sheet_name=sheet_name)
                    if 'EAN' not in df.columns:
                        df.columns = df.iloc[0]
                        df = df.iloc[1:].reset_index(drop=True)
                    st.session_state.motherbase = df
                    st.success(f"✅ Loaded {len(df)} products")
                    if 'Category' in df.columns:
                        st.dataframe(df['Category'].value_counts(), use_container_width=True)
                except Exception as e:
                    st.error(f"Error: {e}")
        else:
            sheets_url = st.text_input("Google Sheets URL")
            if sheets_url and st.button("🔗 Load"):
                df = load_google_sheet(sheets_url)
                if df is not None:
                    if 'EAN' not in df.columns:
                        df.columns = df.iloc[0]
                        df = df.iloc[1:].reset_index(drop=True)
                    st.session_state.motherbase = df
                    st.success(f"✅ Loaded {len(df)} products")
    
    # Tab 3: Container Setup
    with tab3:
        st.header("Container Information")
        col1, col2 = st.columns(2)
        st.session_state.container_info['container_id'] = col1.text_input("Container ID", value=st.session_state.container_info.get('container_id', ''))
        st.session_state.container_info['total_freight_eur'] = col1.number_input("Total Freight (EUR)", min_value=0.0, value=float(st.session_state.container_info.get('total_freight_eur', 0)), step=100.0)
        st.session_state.container_info['total_cbm'] = col2.number_input("Total CBM", min_value=0.0, value=float(st.session_state.container_info.get('total_cbm', 0)), step=0.1)
        col2.date_input("Arrival Date", value=datetime.now())
    
    # Tab 4: Supplier Orders
    with tab4:
        st.header("Supplier Orders")
        
        with st.expander("➕ Add New Supplier Order", expanded=True):
            col1, col2 = st.columns(2)
            supplier_name = col1.text_input("Supplier Name", key="new_supplier_name")
            order_number = col1.text_input("Order Number", key="new_order_number")
            invoice_total_usd = col2.number_input("Invoice Total (USD)", min_value=0.0, key="invoice_total_usd", help="Total from Commercial Invoice")
            
            st.markdown("---")
            st.subheader("💰 Payments (enter EUR amounts from bank statements)")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Payment 1 (Deposit)**")
                p1_eur = st.number_input("Amount Paid (EUR)", min_value=0.0, key="p1_eur")
                p1_date = st.date_input("Date", key="p1_date")
            
            with col2:
                st.markdown("**Payment 2 (Balance)**")
                p2_eur = st.number_input("Amount Paid (EUR)", min_value=0.0, key="p2_eur")
                p2_date = st.date_input("Date", key="p2_date")
            
            total_eur = p1_eur + p2_eur
            if total_eur > 0:
                fx_info = f" (avg FX: {total_eur/invoice_total_usd:.4f})" if invoice_total_usd > 0 else ""
                st.success(f"**Total Paid: €{total_eur:,.2f}**{fx_info}")
            
            st.markdown("---")
            st.subheader("📄 Upload Documents (Optional)")
            doc_col1, doc_col2 = st.columns(2)
            with doc_col1:
                ci_file = st.file_uploader("Commercial Invoice (CI)", type=['xlsx', 'xls', 'pdf'], key="ci_upload")
            with doc_col2:
                pl_file = st.file_uploader("Packing List (PL)", type=['xlsx', 'xls', 'pdf'], key="pl_upload")
            
            # Parse uploaded files
            if ci_file or pl_file:
                st.markdown("### 📊 Extracted Data")
                
                if ci_file and ci_file.name.endswith(('.xlsx', '.xls')):
                    try:
                        ci_df = pd.read_excel(ci_file)
                        # Find header row with Description
                        header_row = None
                        for idx, row in ci_df.iterrows():
                            if any('Description' in str(val) for val in row.values if pd.notna(val)):
                                header_row = idx
                                break
                        if header_row is not None:
                            st.write("**From CI:**")
                            st.dataframe(ci_df.iloc[header_row+1:header_row+20], use_container_width=True)
                    except Exception as e:
                        st.warning(f"Could not parse CI: {e}")
                
                if pl_file and pl_file.name.endswith(('.xlsx', '.xls')):
                    try:
                        pl_df = pd.read_excel(pl_file)
                        header_row = None
                        for idx, row in pl_df.iterrows():
                            if any('Description' in str(val) or 'Carton' in str(val) for val in row.values if pd.notna(val)):
                                header_row = idx
                                break
                        if header_row is not None:
                            st.write("**From PL:**")
                            st.dataframe(pl_df.iloc[header_row+1:header_row+20], use_container_width=True)
                    except Exception as e:
                        st.warning(f"Could not parse PL: {e}")
                
                st.info("💡 Copy the relevant data from above into the line items below")
            
            st.markdown("---")
            st.markdown("### 📝 Line Items")
            st.markdown("`Product Code | Quantity | Unit Price (USD) | CBM`")
            manual_items = st.text_area("One item per line", height=150, placeholder="TP-MA4U4E Black | 1800 | 7.23 | 4.25", key="manual_items")
            
            if st.button("✅ Add Order", type="primary"):
                if supplier_name and order_number:
                    parsed_items = []
                    for line in manual_items.strip().split('\n'):
                        if '|' in line:
                            parts = [p.strip() for p in line.split('|')]
                            if len(parts) >= 3:
                                parsed_items.append({
                                    'product_code': parts[0], 'description': parts[0],
                                    'quantity': int(float(parts[1])), 'unit_price_usd': float(parts[2]),
                                    'cbm': float(parts[3]) if len(parts) > 3 else 0
                                })
                    
                    st.session_state.supplier_orders.append({
                        'supplier_name': supplier_name,
                        'order_number': order_number,
                        'invoice_total_usd': invoice_total_usd,
                        'payment_1': {'amount_eur': p1_eur, 'date': str(p1_date)} if p1_eur > 0 else None,
                        'payment_2': {'amount_eur': p2_eur, 'date': str(p2_date)} if p2_eur > 0 else None,
                        'line_items': parsed_items
                    })
                    st.success(f"Added order {order_number}")
                    st.rerun()
        
        st.markdown("---")
        st.subheader("Current Orders")
        for i, order in enumerate(st.session_state.supplier_orders):
            with st.expander(f"📦 {order['supplier_name']} - #{order['order_number']}"):
                total_paid = (order.get('payment_1', {}) or {}).get('amount_eur', 0) + (order.get('payment_2', {}) or {}).get('amount_eur', 0)
                st.write(f"**Total Paid:** €{total_paid:,.2f}")
                if order.get('line_items'):
                    st.dataframe(pd.DataFrame(order['line_items']), use_container_width=True)
                if st.button("🗑️ Remove", key=f"remove_{i}"):
                    st.session_state.supplier_orders.pop(i)
                    st.rerun()
    
    # Tab 5: Product Matching
    with tab5:
        st.header("Product Matching")
        if st.session_state.motherbase is None:
            st.warning("⚠️ Upload Motherbase first")
        elif not st.session_state.supplier_orders:
            st.warning("⚠️ Add supplier orders first")
        else:
            all_items = []
            for order in st.session_state.supplier_orders:
                for item in order.get('line_items', []):
                    item_copy = item.copy()
                    item_copy['supplier'] = order['supplier_name']
                    all_items.append(item_copy)
            
            matched, unmatched = [], []
            for item in all_items:
                match = match_product(item.get('product_code', ''), st.session_state.motherbase)
                if match:
                    item['ean'] = match.get('EAN', '')
                    item['category'] = match.get('Category', 'Other')
                    matched.append(item)
                else:
                    unmatched.append(item)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total", len(all_items))
            col2.metric("Matched", len(matched))
            col3.metric("Unmatched", len(unmatched))
            
            if matched:
                st.subheader("✅ Matched")
                st.dataframe(pd.DataFrame(matched), use_container_width=True)
            
            if unmatched:
                st.subheader("❌ Unmatched - Select EAN manually")
                for i, item in enumerate(unmatched):
                    col1, col2 = st.columns([2, 1])
                    col1.write(f"**{item.get('product_code')}** - Qty: {item.get('quantity')}")
                    ean = col2.selectbox("EAN", [''] + st.session_state.motherbase['EAN'].astype(str).tolist(), key=f"ean_{i}")
                    if ean:
                        item['ean'] = ean
                        item['category'] = st.session_state.motherbase[st.session_state.motherbase['EAN'].astype(str) == ean].iloc[0].get('Category', 'Other')
                        matched.append(item)
            
            # Update orders with matched data
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
            st.warning("⚠️ Add supplier orders first")
        elif st.session_state.container_info.get('total_freight_eur', 0) == 0:
            st.warning("⚠️ Enter freight cost first")
        else:
            if st.session_state.container_info.get('total_cbm', 0) == 0:
                st.session_state.container_info['total_cbm'] = sum(
                    item.get('cbm', 0) for o in st.session_state.supplier_orders for item in o.get('line_items', [])
                )
            
            results_df = calculate_landed_costs(
                st.session_state.supplier_orders, st.session_state.motherbase,
                st.session_state.container_info, st.session_state.import_duties
            )
            
            if not results_df.empty:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Products", len(results_df))
                col2.metric("Units", f"{results_df['Quantity'].sum():,}")
                col3.metric("Total Value", f"€{results_df['Total Value (EUR)'].sum():,.2f}")
                col4.metric("Avg Cost", f"€{results_df['Landed Cost/Unit (EUR)'].mean():.2f}")
                
                st.dataframe(results_df, use_container_width=True)
                
                export_buffer = pd.io.common.BytesIO()
                with pd.ExcelWriter(export_buffer, engine='openpyxl') as writer:
                    results_df.to_excel(writer, sheet_name='Landed Costs', index=False)
                export_buffer.seek(0)
                
                st.download_button("📥 Download Excel", export_buffer, f"landed_costs_{datetime.now().strftime('%Y%m%d')}.xlsx")

if __name__ == "__main__":
    main()
