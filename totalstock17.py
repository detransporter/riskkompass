import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

# --- CONFIGURATION ---
st.set_page_config(page_title="Warehouse & Analytics Pro", layout="wide")

# File paths
COMMENTS_FILE = 'kommentarer.csv'
MASTER_FILE = 'masterandstock.parquet'
TRANSACTION_FILE = 'transaction_flow.parquet'
PAX_FILE = 'pax_data.parquet'

# Currency rates (SEK)
CURRENCY_RATES = {
    'SEK': 1.0,
    'EUR': 11.5,
    'DKK': 1.55,
    'NOK': 1.05,
    'USD': 10.5
}

# Cost constants
PALLET_COST_PER_MONTH = 100  # SEK per pallet/month

# Hub mappings
HUB_MAPPING = {
    'MAIN': 'MAIN',
    'CPH SAS': 'CPH',
    'ARN SAS': 'ARN',
    'OSL SAS': 'OSL',
    'GOT': 'GOT'
}

# ABC classification thresholds
ABC_A_THRESHOLD = 0.80  # 80% of rows
ABC_B_THRESHOLD = 0.95  # 95% of rows

# Color scheme for ABC
ABC_COLORS = {
    'A': '#00CC96',
    'B': '#636EFA',
    'C': '#EF553B'
}

# --- HELPER FUNCTIONS ---
def find_column(df, possible_names, case_sensitive=False):
    """
    Find column in dataframe based on multiple possible names.
    Returns the first matching column name, or None if none found.

    Args:
        df: DataFrame to search in
        possible_names: List of possible column names to look for
        case_sensitive: If True, do exact matching. If False, ignore case

    Returns:
        The column name that was found, or None
    """
    if not case_sensitive:
        df_cols_lower = {col.lower(): col for col in df.columns}
        for name in possible_names:
            name_lower = name.lower()
            # Exact matching first
            if name_lower in df_cols_lower:
                return df_cols_lower[name_lower]
        # Partial matching if no exact match
        for name in possible_names:
            name_lower = name.lower()
            for col_lower, col_original in df_cols_lower.items():
                if name_lower in col_lower or col_lower in name_lower:
                    return col_original
    else:
        for name in possible_names:
            if name in df.columns:
                return name
    return None

def export_button(df, filename):
    csv = df.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
    st.download_button(f"📥 Export {filename} (CSV)", csv, f"{filename.lower()}.csv", "text/csv")

def load_comments():
    if os.path.exists(COMMENTS_FILE):
        return pd.read_csv(COMMENTS_FILE, dtype={'SKU': str})
    return pd.DataFrame(columns=['SKU', 'Kommentar'])

def save_comments(df):
    if 'Kommentar' in df.columns:
        to_save = df[['SKU', 'Kommentar']].copy()
        to_save['Kommentar'] = to_save['Kommentar'].fillna('').astype(str).str.strip()
        to_save = to_save[to_save['Kommentar'] != ""]
        to_save.to_csv(COMMENTS_FILE, index=False)
        return True
    return False

def load_transitions():
    """Load or create transitions tracking file"""
    transitions_file = 'transitions.csv'
    if not os.path.exists(transitions_file):
        df_trans = pd.DataFrame(columns=[
            'Transition_ID', 'GP_Nummer', 'Old_SKU', 'New_SKU',
            'Transition_Type', 'Hard_Date', 'Status',
            'Created_Date', 'Completed_Date', 'Notes'
        ])
        df_trans.to_csv(transitions_file, index=False)
        return df_trans
    return pd.read_csv(transitions_file, parse_dates=['Hard_Date', 'Created_Date', 'Completed_Date'])

def get_lifecycle_badge(status):
    """Returns emoji badge for lifecycle status"""
    badges = {
        'Active': '🟢',
        'Phase In': '🟡',
        'Phase Out': '🟠',
        'Discontinued': '⚫'
    }
    return badges.get(status, '')

def validate_transition(df_master, old_sku, new_sku, transition_type, hard_date=None):
    """Validates transition creation request"""
    errors = []

    # Check SKUs exist
    if old_sku not in df_master['SKU'].values:
        errors.append(f"Old SKU '{old_sku}' not found")
    if new_sku not in df_master['SKU'].values:
        errors.append(f"New SKU '{new_sku}' not found")

    if errors:
        return {'valid': False, 'errors': errors}

    old_prod = df_master[df_master['SKU'] == old_sku].iloc[0]
    new_prod = df_master[df_master['SKU'] == new_sku].iloc[0]

    # Check GP_Nummer match
    if old_prod['GP_Nummer'] != new_prod['GP_Nummer']:
        errors.append(f"GP_Nummer mismatch: {old_prod['GP_Nummer']} ≠ {new_prod['GP_Nummer']}")

    # Check old SKU status
    if old_prod['Lifecycle_Status'] != 'Active':
        errors.append(f"Old SKU status is '{old_prod['Lifecycle_Status']}', must be 'Active'")

    # Check old SKU not already in transition
    if old_prod['Replaced_By_SKU'] and old_prod['Replaced_By_SKU'] != '':
        errors.append(f"Old SKU already being replaced by {old_prod['Replaced_By_SKU']}")

    # Check hard date
    if transition_type == 'Hard':
        if hard_date is None:
            errors.append("Hard transition requires a date")
        elif pd.to_datetime(hard_date) <= pd.Timestamp.now():
            errors.append("Transition date must be in the future")

    return {'valid': len(errors) == 0, 'errors': errors}

def create_transition(df_master, df_transitions, old_sku, new_sku, transition_type, hard_date=None, notes=''):
    """Creates a new product transition"""
    import uuid

    # Validate first
    validation = validate_transition(df_master, old_sku, new_sku, transition_type, hard_date)
    if not validation['valid']:
        return {'success': False, 'errors': validation['errors']}

    # Generate transition ID
    transition_id = str(uuid.uuid4())[:8]

    # Get GP_Nummer from old product
    gp_nummer = df_master.loc[df_master['SKU'] == old_sku, 'GP_Nummer'].iloc[0]

    # Update master data
    df_master.loc[df_master['SKU'] == old_sku, 'Lifecycle_Status'] = 'Phase Out'
    df_master.loc[df_master['SKU'] == old_sku, 'Replaced_By_SKU'] = new_sku
    df_master.loc[df_master['SKU'] == old_sku, 'Transition_Type'] = transition_type
    if hard_date:
        df_master.loc[df_master['SKU'] == old_sku, 'Transition_Date'] = pd.to_datetime(hard_date)

    df_master.loc[df_master['SKU'] == new_sku, 'Lifecycle_Status'] = 'Phase In'
    df_master.loc[df_master['SKU'] == new_sku, 'Replaces_SKU'] = old_sku

    # Create transition record
    new_transition = pd.DataFrame([{
        'Transition_ID': transition_id,
        'GP_Nummer': gp_nummer,
        'Old_SKU': old_sku,
        'New_SKU': new_sku,
        'Transition_Type': transition_type,
        'Hard_Date': pd.to_datetime(hard_date) if hard_date else pd.NaT,
        'Status': 'Active',
        'Created_Date': pd.Timestamp.now(),
        'Completed_Date': pd.NaT,
        'Notes': notes
    }])

    df_transitions = pd.concat([df_transitions, new_transition], ignore_index=True)

    # Save to files
    df_master.to_parquet(MASTER_FILE)
    df_transitions.to_csv('transitions.csv', index=False)

    return {'success': True, 'transition_id': transition_id}

def validate_po_items(df_master, sku_list):
    """Validates purchase order doesn't contain Phase Out/Discontinued items"""
    blocked = []

    for sku in sku_list:
        if sku not in df_master['SKU'].values:
            continue

        product = df_master[df_master['SKU'] == sku].iloc[0]
        if product['Lifecycle_Status'] in ['Phase Out', 'Discontinued']:
            blocked.append({
                'SKU': sku,
                'Description': product['Description'],
                'Status': product['Lifecycle_Status'],
                'Replaced_By': product['Replaced_By_SKU'],
                'GP_Nummer': product['GP_Nummer']
            })

    return blocked

def get_lifecycle_badge(status):
    """Returns emoji badge for lifecycle status"""
    badges = {
        'Active': '🟢',
        'Phase In': '🟡',
        'Phase Out': '🟠',
        'Discontinued': '⚫'
    }
    return badges.get(status, '')

# --- NPI (New Product Introduction) Functions ---

def load_npi_data():
    """Load or create NPI data file"""
    npi_file = 'npi_products.parquet'

    if not os.path.exists(npi_file):
        # Create empty dataframe with all columns
        df_npi = pd.DataFrame(columns=[
            # Administrative
            'NPI_ID', 'Status', 'Created_Date', 'Created_By', 'Submitted_Date',
            'Approved_Date', 'Approved_By', 'Launched_Date', 'Launched_SKU',
            # Supplier fields
            'Date', 'Product_Description', 'Vendor_Article_Number',
            'Master_Vendor_Name', 'Case_Configuration', 'Case_Height_CM',
            'Case_Width_CM', 'Case_Length_CM', 'Case_Volume_M3',
            'Case_Gross_Weight_KG', 'Case_Net_Weight_KG', 'Cases_Per_Pallet',
            'Height_Per_Pallet_CM', 'Cases_Per_Layer_TI', 'Layers_Per_Pallet_HI',
            'Pallet_Type', 'Storage_Condition', 'Shelflife_Production_Days',
            'Guaranteed_Shelflife_Delivery_Days', 'Min_Order_Qty_Cases',
            'Order_Dispatch_Leadtime', 'Lead_Time_Days', 'Duty_Status',
            'Country_Of_Origin', 'Commodity_Code', 'Incoterms',
            'Collection_Address', 'Alcohol_Percent', 'Payment_Terms',
            'Purchase_Price_Case', 'Purchase_Price_Piece',
            'Purchase_Price_Currency', 'Call_Off_Product', 'Call_Off_QTY',
            # SAS fields
            'SAS_Product_Description', 'SAS_GP4_Number', 'SAS_GP4_Part_Name',
            'SAS_Product_Category', 'SAS_Product_Owner',
            # Logent
            'SK_Number',
            # Notes
            'Notes', 'Rejection_Reason'
        ])
        df_npi.to_parquet(npi_file)
        return df_npi

    return pd.read_parquet(npi_file)

def get_npi_status_counts(df_npi):
    """Get counts for each status"""
    if df_npi.empty:
        return {'Draft': 0, 'Submitted': 0, 'Approved': 0, 'Launched': 0, 'Cancelled': 0}
    status_counts = df_npi['Status'].value_counts().to_dict()
    return {
        'Draft': status_counts.get('Draft', 0),
        'Submitted': status_counts.get('Submitted', 0),
        'Approved': status_counts.get('Approved', 0),
        'Launched': status_counts.get('Launched', 0),
        'Cancelled': status_counts.get('Cancelled', 0)
    }

def validate_npi_entry(npi_data):
    """Validates NPI entry before saving/submitting"""
    errors = []
    warnings = []

    # Required fields check
    required_fields = [
        'Product_Description', 'Vendor_Article_Number', 'Master_Vendor_Name',
        'Case_Configuration', 'Storage_Condition'
    ]

    for field in required_fields:
        if not npi_data.get(field) or str(npi_data[field]).strip() == '':
            errors.append(f"{field.replace('_', ' ')} is required")

    # Product Description length
    if len(str(npi_data.get('Product_Description', ''))) > 49:
        errors.append("Product Description must be max 49 characters")

    # Country of Origin format (2-digit ISO)
    country = str(npi_data.get('Country_Of_Origin', '')).strip().upper()
    if country and len(country) != 2:
        errors.append("Country of Origin must be 2-digit ISO code (e.g., SE, DK)")

    # Currency format (3-digit ISO)
    currency = str(npi_data.get('Purchase_Price_Currency', '')).strip().upper()
    if currency and len(currency) != 3:
        errors.append("Currency must be 3-digit ISO code (e.g., EUR, USD, SEK)")

    # Alcohol percentage range
    alcohol = npi_data.get('Alcohol_Percent')
    if alcohol and (alcohol < 0 or alcohol > 100):
        errors.append("Alcohol % must be between 0 and 100")

    # Case configuration minimum
    case_config = npi_data.get('Case_Configuration')
    if case_config and case_config < 1:
        errors.append("Case Configuration must be at least 1")

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }

def validate_npi_for_submission(npi_data):
    """Additional validation before submitting for review"""
    result = validate_npi_entry(npi_data)

    # Submission requires more fields than draft
    additional_required = [
        'Lead_Time_Days', 'Purchase_Price_Case', 'Purchase_Price_Currency',
        'Duty_Status', 'Country_Of_Origin'
    ]

    for field in additional_required:
        if not npi_data.get(field):
            result['errors'].append(f"{field.replace('_', ' ')} required for submission")

    result['valid'] = len(result['errors']) == 0
    return result

def validate_npi_for_approval(npi_data):
    """Validation before approval (SAS fields must be complete)"""
    result = validate_npi_for_submission(npi_data)

    # Approval requires SAS fields
    sas_required = ['SAS_GP4_Number', 'SAS_Product_Category', 'SAS_Product_Owner']

    for field in sas_required:
        if not npi_data.get(field):
            result['errors'].append(f"{field.replace('_', ' ')} required for approval")

    result['valid'] = len(result['errors']) == 0
    return result

def create_npi_entry(df_npi, npi_data):
    """Creates a new NPI entry in Draft status"""
    import uuid

    # Generate NPI ID
    npi_id = f"NPI-{str(uuid.uuid4())[:8].upper()}"

    # Validate
    validation = validate_npi_entry(npi_data)
    if not validation['valid']:
        return {'success': False, 'errors': validation['errors']}

    # Create new row
    new_npi = npi_data.copy()
    new_npi['NPI_ID'] = npi_id
    new_npi['Status'] = 'Draft'
    new_npi['Created_Date'] = pd.Timestamp.now()
    new_npi['Created_By'] = 'System'

    # Add to dataframe
    df_npi = pd.concat([df_npi, pd.DataFrame([new_npi])], ignore_index=True)

    # Save
    df_npi.to_parquet('npi_products.parquet')

    return {'success': True, 'npi_id': npi_id, 'warnings': validation.get('warnings', [])}

def submit_npi(df_npi, npi_id):
    """Submit NPI for review (Draft → Submitted)"""

    # Get NPI
    npi = df_npi[df_npi['NPI_ID'] == npi_id]
    if npi.empty:
        return {'success': False, 'error': 'NPI not found'}

    npi_data = npi.iloc[0].to_dict()

    # Validate for submission
    validation = validate_npi_for_submission(npi_data)
    if not validation['valid']:
        return {'success': False, 'errors': validation['errors']}

    # Update status
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Status'] = 'Submitted'
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Submitted_Date'] = pd.Timestamp.now()

    # Save
    df_npi.to_parquet('npi_products.parquet')

    return {'success': True, 'warnings': validation.get('warnings', [])}

def approve_npi(df_npi, npi_id, approved_by='System'):
    """Approve NPI (Submitted → Approved)"""

    # Get NPI
    npi = df_npi[df_npi['NPI_ID'] == npi_id]
    if npi.empty:
        return {'success': False, 'error': 'NPI not found'}

    npi_data = npi.iloc[0].to_dict()

    # Check status
    if npi_data['Status'] != 'Submitted':
        return {'success': False, 'error': f'NPI must be Submitted (current: {npi_data["Status"]})'}

    # Validate for approval
    validation = validate_npi_for_approval(npi_data)
    if not validation['valid']:
        return {'success': False, 'errors': validation['errors']}

    # Update status
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Status'] = 'Approved'
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Approved_Date'] = pd.Timestamp.now()
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Approved_By'] = approved_by

    # Save
    df_npi.to_parquet('npi_products.parquet')

    return {'success': True, 'warnings': validation.get('warnings', [])}

def launch_npi_to_master(df_master, df_npi, npi_id, new_sku=None):
    """Launch approved NPI as new SKU in master data (Approved → Launched)"""

    # Get NPI
    npi = df_npi[df_npi['NPI_ID'] == npi_id]
    if npi.empty:
        return {'success': False, 'error': 'NPI not found'}

    npi_data = npi.iloc[0].to_dict()

    # Check status
    if npi_data['Status'] != 'Approved':
        return {'success': False, 'error': f'NPI must be Approved (current: {npi_data["Status"]})'}

    # Generate or validate SKU
    if not new_sku:
        # Auto-generate SKU
        new_sku = f"SKU-{npi_data['Vendor_Article_Number']}"

    # Check for duplicate SKU
    if new_sku in df_master['SKU'].values:
        return {'success': False, 'error': f'SKU {new_sku} already exists in master data'}

    # Map NPI fields to master data fields
    new_product = {
        'SKU': new_sku,
        'Description': npi_data['Product_Description'],
        'Supplier': npi_data['Master_Vendor_Name'],
        'GP_Nummer': npi_data['SAS_GP4_Number'],
        'CC': npi_data['Case_Configuration'],
        'Status': 'Active',
        'Lifecycle_Status': 'Phase In',
        'Transition_Type': 'None',
        'Transition_Date': pd.NaT,
        'Replaces_SKU': '',
        'Replaced_By_SKU': '',
        'Leadtime': npi_data.get('Lead_Time_Days', 0),
        'Lager': 'MAIN',
        'Quantity': 0,
    }

    # Add to master data
    df_master = pd.concat([df_master, pd.DataFrame([new_product])], ignore_index=True)
    df_master.to_parquet(MASTER_FILE)

    # Update NPI status
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Status'] = 'Launched'
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Launched_Date'] = pd.Timestamp.now()
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Launched_SKU'] = new_sku
    df_npi.to_parquet('npi_products.parquet')

    return {'success': True, 'sku': new_sku}

def cancel_npi(df_npi, npi_id, reason):
    """Cancel NPI (Any status → Cancelled)"""

    if not reason or reason.strip() == '':
        return {'success': False, 'error': 'Rejection reason required'}

    # Get NPI
    npi = df_npi[df_npi['NPI_ID'] == npi_id]
    if npi.empty:
        return {'success': False, 'error': 'NPI not found'}

    # Update status
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Status'] = 'Cancelled'
    df_npi.loc[df_npi['NPI_ID'] == npi_id, 'Rejection_Reason'] = reason

    # Save
    df_npi.to_parquet('npi_products.parquet')

    return {'success': True}

# --- 2. DATA LOADING ---
@st.cache_data
def load_data():
    try:
        # Master data
        if not os.path.exists(MASTER_FILE):
            st.error(f"❌ File '{MASTER_FILE}' is missing. Check that the file exists in the same folder as the script.")
            st.stop()
        df_m = pd.read_parquet(MASTER_FILE)
        df_m.columns = [c.strip() for c in df_m.columns]

        # Automatic column detection for master data
        case_col = find_column(df_m, ['Case_config', 'CASE_CONFIG', 'Receipt Multiple', 'RECEIPT MULTIPLE', 'Pack Qty', 'PACK_QTY'])
        sku_col = find_column(df_m, ['SKU', 'Item', 'Article', 'Product_ID'])
        desc_col = find_column(df_m, ['Item Description', 'ITEM DESCRIPTION', 'Description', 'Description', 'Product Name'])
        vendor_col = find_column(df_m, ['Warehouse Vendor Name', 'WAREHOUSE VENDOR NAME', 'Vendor', 'Supplier', 'Supplier'])
        gp_col = find_column(df_m, ['GP_Number', 'GP Number', 'GP_NUMBER', 'GP_NUMMER', 'Customer External Reference', 'CUSTOMER EXTERNAL REFERENCE'])
        hub_col = find_column(df_m, ['Hub', 'HUB', 'Warehouse', 'Location', 'Lager'])
        pallet_col = find_column(df_m, ['Pallets', 'PALLETS', 'Pallet_Count'])
        status_col = find_column(df_m, ['Status', 'STATUS', 'Active', 'ACTIVE', 'Item_Status'])
        leadtime_col = find_column(df_m, ['Leadtime', 'LEADTIME', 'Lead_Time', 'Delivery_Time'])
        incoterm_col = find_column(df_m, ['Incoterms', 'INCOTERMS', 'Incoterm', 'Delivery_Terms'])
        qty_col = find_column(df_m, ['Quantity', 'QUANTITY', 'Qty', 'Stock', 'Amount'])
        cost_col = find_column(df_m, ['Cost_Price', 'COST_PRICE', 'Cost', 'Price', 'Unit_Cost'])
        currency_col = find_column(df_m, ['Currency', 'CURRENCY', 'Curr'])

        # Create rename map based on found columns
        rename_map = {}
        if desc_col: rename_map[desc_col] = 'Description'
        if vendor_col: rename_map[vendor_col] = 'Supplier'
        if gp_col: rename_map[gp_col] = 'GP_Nummer'
        if hub_col: rename_map[hub_col] = 'Lager'
        if pallet_col: rename_map[pallet_col] = 'Pallets'
        if status_col: rename_map[status_col] = 'Status'
        if leadtime_col: rename_map[leadtime_col] = 'Leadtime'
        if incoterm_col: rename_map[incoterm_col] = 'Incoterms'
        if qty_col: rename_map[qty_col] = 'Quantity'
        if cost_col: rename_map[cost_col] = 'COST_PRICE'
        if currency_col: rename_map[currency_col] = 'CURRENCY'
        if sku_col: rename_map[sku_col] = 'SKU'

        df_m = df_m.rename(columns=rename_map)

        # Ensure SKU exists
        if 'SKU' not in df_m.columns:
            st.error("❌ SKU column not found in master data. Check the file format.")
            st.stop()

        df_m['SKU'] = df_m['SKU'].astype(str).str.strip()

        for col in ['Description', 'Supplier', 'GP_Nummer', 'Lager', 'Status', 'Leadtime', 'Incoterms']:
            if col not in df_m.columns: df_m[col] = 'saknas'
            else: df_m[col] = df_m[col].fillna('saknas').astype(str)

        # Add lifecycle management fields with defaults
        for col in ['Lifecycle_Status', 'Transition_Type', 'Transition_Date', 'Replaces_SKU', 'Replaced_By_SKU']:
            if col not in df_m.columns:
                if col == 'Lifecycle_Status':
                    df_m[col] = 'Active'
                elif col == 'Transition_Type':
                    df_m[col] = 'None'
                elif col == 'Transition_Date':
                    df_m[col] = pd.NaT  # Null datetime
                else:  # Replaces_SKU, Replaced_By_SKU
                    df_m[col] = ''

        df_m['Quantity'] = pd.to_numeric(df_m['Quantity'], errors='coerce').fillna(0)
        df_m['CC'] = pd.to_numeric(df_m[case_col] if case_col else 1, errors='coerce').fillna(1).replace(0, 1)

        df_m['Lagersaldo_St'] = df_m['Quantity']
        df_m.loc[df_m['Lager'].str.upper() == 'MAIN', 'Lagersaldo_St'] = df_m['Quantity'] * df_m['CC']

        # Use existing Pris_st_SEK from file if available, otherwise calculate
        if 'Pris_st_SEK' in df_m.columns and df_m['Pris_st_SEK'].notna().any():
            # Convert to numeric, preserving existing values
            df_m['Pris_st_SEK'] = pd.to_numeric(df_m['Pris_st_SEK'], errors='coerce')

            # Only fill NaN values if we have cost price data to calculate from
            if 'COST_PRICE' in df_m.columns and 'CURRENCY' in df_m.columns:
                # Calculate cost_price and Rate for filling missing Pris_st_SEK
                cost_price_col = df_m['COST_PRICE']
                if isinstance(cost_price_col, pd.Series):
                    df_m['cost_price'] = pd.to_numeric(cost_price_col, errors='coerce')
                else:
                    df_m['cost_price'] = 0

                df_m['Rate'] = df_m['CURRENCY'].str.upper().map(CURRENCY_RATES).fillna(1.0)

                # Only fill NaN values with calculated price
                calculated_price = (df_m['cost_price'] * df_m['Rate']) / df_m['CC']
                df_m['Pris_st_SEK'] = df_m['Pris_st_SEK'].fillna(calculated_price)
            else:
                # No calculation data available, fill remaining NaN with 0
                df_m['Pris_st_SEK'] = df_m['Pris_st_SEK'].fillna(0)
        else:
            # Pris_st_SEK doesn't exist, calculate from scratch
            if 'COST_PRICE' in df_m.columns:
                cost_price_col = df_m['COST_PRICE']
                if isinstance(cost_price_col, pd.Series):
                    df_m['cost_price'] = pd.to_numeric(cost_price_col, errors='coerce').fillna(0)
                else:
                    df_m['cost_price'] = 0
            else:
                df_m['cost_price'] = 0

            if 'CURRENCY' in df_m.columns:
                df_m['Rate'] = df_m['CURRENCY'].str.upper().map(CURRENCY_RATES).fillna(1.0)
            else:
                df_m['Rate'] = 1.0

            df_m['Pris_st_SEK'] = (df_m['cost_price'] * df_m['Rate']) / df_m['CC']

        # Transaction data
        if not os.path.exists(TRANSACTION_FILE):
            st.error(f"❌ File '{TRANSACTION_FILE}' is missing. Check that the file exists in the same folder as the script.")
            st.stop()
        df_t = pd.read_parquet(TRANSACTION_FILE)
        df_t.columns = [c.strip() for c in df_t.columns]

        # Automatic column detection for transaction data
        sku_col_t = find_column(df_t, ['SKU', 'Item', 'Article', 'Product_ID'])
        qty_col_t = find_column(df_t, ['Qty', 'QTY', 'Quantity', 'QUANTITY', 'Amount'])
        event_col = find_column(df_t, ['Event_Date', 'EVENT_DATE', 'Date', 'Transaction_Date', 'Order Date', 'OrderDate'])
        flow_col = find_column(df_t, ['Flow_Type', 'FLOW_TYPE', 'Type', 'Transaction_Type'])
        customer_col = find_column(df_t, ['Customer', 'CUSTOMER', 'Client', 'Customer_Name'])
        order_status_col = find_column(df_t, ['Order Row Status', 'ORDER ROW STATUS', 'OrderRowStatus', 'Status', 'Row_Status'])
        confirmed_qty_col = find_column(df_t, ['ConfirmedQty (Cases)', 'CONFIRMEDQTY (CASES)', 'Confirmed_Qty', 'Confirmed Quantity'])
        deliv_qty_col = find_column(df_t, ['DelivQty (Cases)', 'DELIVQTY (CASES)', 'Delivered_Qty', 'Delivered Quantity', 'DeliveredQuantity'])

        # Skapa rename map
        rename_map_t = {}
        if sku_col_t: rename_map_t[sku_col_t] = 'SKU'
        if qty_col_t: rename_map_t[qty_col_t] = 'QTY_ORIG'
        if event_col: rename_map_t[event_col] = 'EVENT_DATE'
        if flow_col: rename_map_t[flow_col] = 'FLOW_TYPE'
        if customer_col: rename_map_t[customer_col] = 'CUSTOMER'
        if order_status_col: rename_map_t[order_status_col] = 'ORDER_ROW_STATUS'
        if confirmed_qty_col: rename_map_t[confirmed_qty_col] = 'CONFIRMEDQTY'
        if deliv_qty_col: rename_map_t[deliv_qty_col] = 'DELIVQTY'

        df_t = df_t.rename(columns=rename_map_t)

        # Ensure critical columns exist
        if 'SKU' not in df_t.columns:
            st.error("❌ SKU column not found in transaction data.")
            st.stop()
        if 'EVENT_DATE' not in df_t.columns:
            st.error("❌ Date column not found in transaction data.")
            st.stop()
        if 'FLOW_TYPE' not in df_t.columns:
            st.error("❌ Flow Type column not found in transaction data.")
            st.stop()

        df_t['SKU'] = df_t['SKU'].astype(str).str.strip()
        df_t['EVENT_DATE'] = pd.to_datetime(df_t['EVENT_DATE'])
        df_t['FLOW_TYPE'] = df_t['FLOW_TYPE'].astype(str).str.strip().str.upper()

        if 'CUSTOMER' in df_t.columns:
            df_t['CUSTOMER'] = df_t['CUSTOMER'].fillna('saknas').astype(str)
        else:
            df_t['CUSTOMER'] = 'saknas'

        # Pax data
        if not os.path.exists(PAX_FILE):
            st.error(f"❌ File '{PAX_FILE}' is missing. Check that the file exists in the same folder as the script.")
            st.stop()
        df_pax = pd.read_parquet(PAX_FILE)

        return df_m, df_t, df_pax

    except Exception as e:
        st.error(f"❌ Error loading data: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        st.stop()

df_master, df_trans, df_pax = load_data()
df_transitions = load_transitions()
df_npi = load_npi_data()

# --- 3. GLOBAL FILTERS ---
st.sidebar.header("🔍 Global Filters")
g_sku = st.sidebar.text_input("Search SKU")
g_gp = st.sidebar.text_input("Search GP Number")
g_desc = st.sidebar.text_input("Search Description")
all_suppliers = sorted([str(x) for x in df_master['Supplier'].unique()])
all_statuses = sorted([str(x) for x in df_master['Status'].unique()])
g_supp = st.sidebar.multiselect("Supplier", all_suppliers)
g_status = st.sidebar.multiselect("Status", all_statuses)

# Debug info (can be expanded)
with st.sidebar.expander("🔧 Column Detection"):
    st.caption("**Master Data:**")
    st.text(f"✓ SKU: found")
    st.text(f"✓ Description: {'found' if 'Description' in df_master.columns else 'missing'}")
    st.text(f"✓ Status: {'found' if 'Status' in df_master.columns else 'missing'}")
    st.text(f"✓ Warehouse: {'found' if 'Lager' in df_master.columns else 'missing'}")
    st.caption("**Transaction Data:**")
    st.text(f"✓ SKU: found")
    st.text(f"✓ FLOW_TYPE: found")
    st.text(f"✓ Order Status: {'found' if 'ORDER_ROW_STATUS' in df_trans.columns else 'missing'}")
    st.text(f"✓ ConfirmedQty: {'found' if 'CONFIRMEDQTY' in df_trans.columns else 'missing'}")
    st.text(f"✓ DelivQty: {'found' if 'DELIVQTY' in df_trans.columns else 'missing'}")

def apply_filters(df):
    df_f = df.copy()
    sku_col = 'SKU' if 'SKU' in df_f.columns else None
    gp_col = 'GP_Nummer' if 'GP_Nummer' in df_f.columns else None
    desc_col = 'Description' if 'Description' in df_f.columns else None
    if g_sku and sku_col: df_f = df_f[df_f[sku_col].str.contains(g_sku, case=False, na=False)]
    if g_gp and gp_col: df_f = df_f[df_f[gp_col].astype(str).str.contains(g_gp, case=False, na=False)]
    if g_desc and desc_col: df_f = df_f[df_f[desc_col].str.contains(g_desc, case=False, na=False)]
    if g_supp and 'Supplier' in df_f.columns: df_f = df_f[df_f['Supplier'].isin(g_supp)]
    if g_status and 'Status' in df_f.columns: df_f = df_f[df_f['Status'].isin(g_status)]
    return df_f

# --- 4. CORE CALCULATIONS ---
df_sales_all = df_trans[df_trans['FLOW_TYPE'] == 'SALES'].copy()
last_sale_date = df_sales_all['EVENT_DATE'].max()
if pd.isna(last_sale_date): last_sale_date = datetime.now()

today_now = datetime.now()
curr_m_str, last_y_m_str = today_now.strftime('%Y-%m'), (today_now - timedelta(days=365)).strftime('%Y-%m')
pax_factor = 0.0
if curr_m_str in df_pax.columns and last_y_m_str in df_pax.columns:
    pax_now, pax_then = df_pax[curr_m_str].sum(), df_pax[last_y_m_str].sum()
    if pax_then > 0: pax_factor = (pax_now - pax_then) / pax_then

df_cc_map = df_master[['SKU', 'CC', 'Pris_st_SEK']].drop_duplicates('SKU')
t1, t2 = last_sale_date - timedelta(days=30), last_sale_date
df_actual_30 = df_sales_all[(df_sales_all['EVENT_DATE'] >= t1) & (df_sales_all['EVENT_DATE'] <= t2)].copy()
df_actual_30 = pd.merge(df_actual_30, df_cc_map, on='SKU', how='left')
df_actual_30['Qty_st'] = pd.to_numeric(df_actual_30['QTY_ORIG'], errors='coerce').fillna(0) * df_actual_30['CC'].fillna(1)
actual_sum = df_actual_30.groupby('SKU')['Qty_st'].sum()

df_abc_data = df_actual_30.groupby('SKU').size().reset_index(name='Rader')
df_abc_data['ABC'] = 'C'
if not df_abc_data.empty:
    df_abc_data = df_abc_data.sort_values(by='Rader', ascending=False)
    df_abc_data['cum_pct'] = df_abc_data['Rader'].cumsum() / df_abc_data['Rader'].sum()
    # Vectorized ABC classification instead of apply
    df_abc_data['ABC'] = 'C'
    df_abc_data.loc[df_abc_data['cum_pct'] <= ABC_B_THRESHOLD, 'ABC'] = 'B'
    df_abc_data.loc[df_abc_data['cum_pct'] <= ABC_A_THRESHOLD, 'ABC'] = 'A'

t3 = t1 - timedelta(days=30)
df_ref_30 = df_sales_all[(df_sales_all['EVENT_DATE'] >= t3) & (df_sales_all['EVENT_DATE'] < t1)].copy()
df_ref_30 = pd.merge(df_ref_30, df_cc_map, on='SKU', how='left')
df_ref_30['Qty_st'] = pd.to_numeric(df_ref_30['QTY_ORIG'], errors='coerce').fillna(0) * df_ref_30['CC'].fillna(1)
ref_sum = df_ref_30.groupby('SKU')['Qty_st'].sum()

df_metrics = pd.DataFrame(index=df_master['SKU'].unique())
df_metrics['Actual_30d'] = df_metrics.index.map(actual_sum).fillna(0)
df_metrics['Ref_30d'] = df_metrics.index.map(ref_sum).fillna(0)
df_metrics['Snitt_30d'] = df_metrics['Actual_30d'] / 30
df_metrics['Snitt_Prog'] = df_metrics['Snitt_30d'] * (1 + pax_factor)
df_metrics['MAE'] = abs(df_metrics['Actual_30d'] - (df_metrics['Ref_30d'] * (1 + pax_factor)))
df_metrics['MAPE'] = np.where(df_metrics['Actual_30d'] > 0, (df_metrics['MAE'] / df_metrics['Actual_30d']) * 100, 0)

df_main = df_master[df_master['Lager'].str.upper() == 'MAIN'].groupby('SKU').agg({'Lagersaldo_St': 'sum', 'Pallets': 'sum'}).reset_index().rename(columns={'Lagersaldo_St': 'Saldo_MAIN'})

# --- UPDATED PO LOGIC ---
df_po = df_trans[df_trans['FLOW_TYPE'] == 'PO'].copy()

# Filter by order row status: 'Sent' or 'PartlyDelivered'
if not df_po.empty and 'ORDER_ROW_STATUS' in df_po.columns:
    df_po = df_po[df_po['ORDER_ROW_STATUS'].isin(['Sent', 'PartlyDelivered'])]

# Use ConfirmedQty (Cases) - DelivQty (Cases) and convert to pieces with case_config
if not df_po.empty:
    # Merge with CC (case_config) from master data
    df_po = pd.merge(df_po, df_cc_map[['SKU', 'CC']], on='SKU', how='left')

    po_confirmed_vals = pd.to_numeric(df_po['CONFIRMEDQTY'], errors='coerce').fillna(0) if 'CONFIRMEDQTY' in df_po.columns else pd.Series(0.0, index=df_po.index)
    po_deliv_vals = pd.to_numeric(df_po['DELIVQTY'], errors='coerce').fillna(0) if 'DELIVQTY' in df_po.columns else pd.Series(0.0, index=df_po.index)

    # Calculate remaining in cases, then convert to pieces
    df_po['Rest_Cases'] = po_confirmed_vals - po_deliv_vals
    df_po['Rest_st'] = df_po['Rest_Cases'] * df_po['CC'].fillna(1)

    df_po_res = df_po[df_po['Rest_st'] > 0].groupby('SKU').agg({'Rest_st': 'sum', 'EVENT_DATE': 'min'}).reset_index().rename(columns={'EVENT_DATE': 'PO_Datum'})
else:
    # Create empty dataframe if no PO data
    df_po_res = pd.DataFrame(columns=['SKU', 'Rest_st', 'PO_Datum'])

# D. Master view
df_final = df_master[['SKU', 'Description', 'Supplier', 'GP_Nummer', 'Status', 'Pris_st_SEK', 'CC', 'Leadtime', 'Incoterms']].drop_duplicates('SKU')
df_final = df_final.rename(columns={'CC': 'Case_config'})
df_final = df_final.merge(df_main, on='SKU', how='left').merge(df_metrics.reset_index().rename(columns={'index':'SKU'}), on='SKU', how='left').merge(df_abc_data[['SKU', 'ABC']], on='SKU', how='left').merge(df_po_res, on='SKU', how='left').merge(load_comments(), on='SKU', how='left')
df_final[['Saldo_MAIN', 'Pallets', 'Snitt_30d', 'Actual_30d', 'Snitt_Prog', 'Rest_st', 'MAE', 'MAPE']] = df_final[['Saldo_MAIN', 'Pallets', 'Snitt_30d', 'Actual_30d', 'Snitt_Prog', 'Rest_st', 'MAE', 'MAPE']].fillna(0)
df_final['ABC'] = df_final['ABC'].fillna('C')
df_final['Days_on_Stock'] = np.where(df_final['Snitt_Prog'] > 0, df_final['Saldo_MAIN'] / df_final['Snitt_Prog'], np.inf)
# Vectorized calculation of Slutdatum instead of apply
days_capped = np.minimum(df_final['Days_on_Stock'].replace([np.inf], np.nan), 3650)
df_final['Slutdatum'] = pd.to_datetime(today_now) + pd.to_timedelta(days_capped, unit='D')
df_final['Slutdatum'] = df_final['Slutdatum'].dt.date
df_final.loc[df_final['Days_on_Stock'] == np.inf, 'Slutdatum'] = None

# --- 5. UI ---
tabs = st.tabs(["🏠 Dashboard", "📦 Stock Balance", "📥 Inbound", "📤 Outbound", "⚠️ Stock Risk", "📊 Analysis", "🔍 Customer Search", "🔄 Lifecycle", "🆕 NPI", "⚙️ Settings"])

with tabs[0]:
    st.header("Warehouse Overview (MAIN)")
    f = apply_filters(df_final)
    k1, k2, k3, k4, k5 = st.columns(5)
    total_val = (f['Saldo_MAIN']*f['Pris_st_SEK']).sum()
    k1.metric("Inventory Value", f"{total_val:,.0f} SEK".replace(",", " "))
    k2.metric("Number of Pallets", f"{int(f['Pallets'].sum())} pcs")
    k3.metric("3PL Rent / Month", f"{f['Pallets'].sum()*PALLET_COST_PER_MONTH:,.0f} SEK".replace(",", " "))
    k4.metric("Forecast Error (MAE)", f"{f['MAE'].mean():.1f} pcs")
    k5.metric("Forecast Error (MAPE)", f"{f[f['Actual_30d']>0]['MAPE'].mean():.1f} %")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("ABC Distribution (Count)")
        st.plotly_chart(px.pie(f, names='ABC', hole=0.4, color='ABC', color_discrete_map=ABC_COLORS), use_container_width=True)
    with c2:
        st.subheader("Inventory Value per Hub (SEK)")
        h_data = apply_filters(df_master[df_master['Lager'].isin(HUB_MAPPING.keys())].copy())
        h_data['Value'] = h_data['Lagersaldo_St'] * h_data['Pris_st_SEK']
        h_val = h_data.groupby('Lager')['Value'].sum().reset_index()
        h_val['Lager'] = h_val['Lager'].map(HUB_MAPPING)
        st.plotly_chart(px.bar(h_val, x='Lager', y='Value', color='Lager', text_auto='.2s'), use_container_width=True)

with tabs[1]:
    st.header("Stock Balance per Hub (pcs)")
    df_h = df_master[df_master['Lager'].isin(HUB_MAPPING.keys())].pivot_table(index='SKU', columns='Lager', values='Lagersaldo_St', aggfunc='sum').fillna(0).rename(columns=HUB_MAPPING)
    full_stock_df = df_final.merge(df_h, on='SKU', how='left')

    # Add lifecycle badge column
    if 'Lifecycle_Status' in full_stock_df.columns:
        full_stock_df['Lifecycle'] = full_stock_df['Lifecycle_Status'].apply(lambda x: f"{get_lifecycle_badge(x)} {x}")
        cols_order = ['SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle', 'Status', 'ABC', 'Days_on_Stock', 'Slutdatum', 'MAIN', 'CPH', 'ARN', 'OSL', 'GOT', 'Pallets', 'Case_config', 'Leadtime', 'Incoterms', 'Pris_st_SEK', 'Rest_st', 'PO_Datum', 'Kommentar']
    else:
        cols_order = ['SKU', 'GP_Nummer', 'Description', 'Supplier', 'Status', 'ABC', 'Days_on_Stock', 'Slutdatum', 'MAIN', 'CPH', 'ARN', 'OSL', 'GOT', 'Pallets', 'Case_config', 'Leadtime', 'Incoterms', 'Pris_st_SEK', 'Rest_st', 'PO_Datum', 'Kommentar']

    final_cols = [c for c in cols_order if c in full_stock_df.columns]
    view_stock = apply_filters(full_stock_df[final_cols])
    st.dataframe(view_stock, hide_index=True, use_container_width=True,
                column_config={
                    "Pris_st_SEK": st.column_config.NumberColumn("Price/pcs (SEK)", format="%.2f kr"),
                    "Lifecycle": st.column_config.TextColumn("Lifecycle", help="Product lifecycle status")
                })
    export_button(view_stock, "Stock_Balance")

with tabs[2]:
    st.header("📥 Inbound Orders - Incoming Goods")

    # Get all POs from transaction data
    df_inbound = df_trans[df_trans['FLOW_TYPE'] == 'PO'].copy()

    if df_inbound.empty:
        st.warning("⚠️ No inbound data (PO) found in transaction data.")
    else:
        # Find relevant columns
        po_num_col = find_column(df_inbound, ['PurchaseOrderNo', 'PO_Number', 'Order_Number'])
        order_line_col = find_column(df_inbound, ['OrderLineNo', 'Line_Number'])
        supplier_col = find_column(df_inbound, ['Supplier', 'Vendor', 'Supplier'])
        gp_col = find_column(df_inbound, ['GP Number', 'GP_Number', 'GP_Nummer'])
        confirmed_col = find_column(df_inbound, ['CONFIRMEDQTY', 'ConfirmedQty (Cases)', 'Confirmed_Qty', 'ConfirmedQty'])
        delivered_col = find_column(df_inbound, ['DELIVQTY', 'DelivQty (Cases)', 'DelivQty', 'Delivered_Qty', 'Qty', 'QTY'])
        order_date_col = find_column(df_inbound, ['Order Date', 'OrderDate', 'Order_Date'])
        deliv_date_col = find_column(df_inbound, ['Original Deliv Date', 'OriginalDeliveryDate', 'Delivery_Date'])
        event_date_col = find_column(df_inbound, ['Event_Date', 'EVENT_DATE', 'Event Date'])
        status_col = find_column(df_inbound, ['Order Row Status', 'Status', 'Order_Status'])
        price_col = find_column(df_inbound, ['Purchase Price', 'Purchase_Price', 'Unit_Price'])
        currency_col = find_column(df_inbound, ['Currency', 'CURRENCY', 'Curr'])

        # Create rename map
        rename_inbound = {}
        if po_num_col: rename_inbound[po_num_col] = 'PO_Number'
        if order_line_col: rename_inbound[order_line_col] = 'Line_No'
        if supplier_col: rename_inbound[supplier_col] = 'Supplier'
        if gp_col: rename_inbound[gp_col] = 'GP_Nummer'
        if confirmed_col: rename_inbound[confirmed_col] = 'Confirmed_Cases'
        if delivered_col: rename_inbound[delivered_col] = 'Delivered_Cases'
        if order_date_col: rename_inbound[order_date_col] = 'Order_Date'
        # Original Deliv Date not used - EVENT_DATE contains all date information
        # if deliv_date_col: rename_inbound[deliv_date_col] = 'Planned_Delivery_Date'
        if event_date_col: rename_inbound[event_date_col] = 'Actual_Delivery_Date'
        if status_col: rename_inbound[status_col] = 'PO_Status'
        if price_col: rename_inbound[price_col] = 'Purchase_Price'
        if currency_col: rename_inbound[currency_col] = 'Currency'

        df_inbound = df_inbound.rename(columns=rename_inbound)

        # Ensure columns exist
        for col in ['PO_Number', 'Supplier', 'GP_Nummer', 'Confirmed_Cases', 'Delivered_Cases', 'Order_Date', 'Actual_Delivery_Date', 'PO_Status', 'Purchase_Price', 'Currency']:
            if col not in df_inbound.columns:
                if col == 'Confirmed_Cases' or col == 'Delivered_Cases':
                    df_inbound[col] = 0
                elif col == 'Purchase_Price':
                    df_inbound[col] = 0.0
                elif col in ['Order_Date', 'Actual_Delivery_Date']:
                    df_inbound[col] = pd.NaT
                else:
                    df_inbound[col] = 'saknas'

        # Convert dates
        df_inbound['Order_Date'] = pd.to_datetime(df_inbound['Order_Date'], errors='coerce')
        df_inbound['Actual_Delivery_Date'] = pd.to_datetime(df_inbound['Actual_Delivery_Date'], errors='coerce')

        # Merge with master to get CC, price, and lifecycle status
        master_cols_for_inbound = ['SKU', 'CC', 'Description', 'Pris_st_SEK', 'Leadtime']
        if 'Lifecycle_Status' in df_master.columns:
            master_cols_for_inbound.append('Lifecycle_Status')
        if 'Replaced_By_SKU' in df_master.columns:
            master_cols_for_inbound.append('Replaced_By_SKU')
        df_inbound = pd.merge(df_inbound, df_master[master_cols_for_inbound].drop_duplicates('SKU'), on='SKU', how='left')

        # Calculate quantities in pieces
        df_inbound['Confirmed_Cases'] = pd.to_numeric(df_inbound['Confirmed_Cases'], errors='coerce').fillna(0)
        df_inbound['Delivered_Cases'] = pd.to_numeric(df_inbound['Delivered_Cases'], errors='coerce')
        df_inbound['Confirmed_St'] = df_inbound['Confirmed_Cases'] * df_inbound['CC'].fillna(1)

        # For FullyDelivered orders where DELIVQTY is missing: assume everything is delivered
        # For other orders where DELIVQTY is missing: assume 0 delivered
        df_inbound['Actual_Delivered_Cases'] = df_inbound.apply(
            lambda row: row['Confirmed_Cases'] if row['PO_Status'] == 'FullyDelivered' and pd.isna(row['Delivered_Cases'])
            else (row['Delivered_Cases'] if pd.notna(row['Delivered_Cases']) else 0),
            axis=1
        )
        df_inbound['Delivered_St'] = df_inbound['Actual_Delivered_Cases'] * df_inbound['CC'].fillna(1)
        df_inbound['Outstanding_St'] = df_inbound['Confirmed_St'] - df_inbound['Delivered_St']
        df_inbound['Outstanding_Cases'] = df_inbound['Confirmed_Cases'] - df_inbound['Actual_Delivered_Cases']

        # Use Order Row Status directly from data
        df_inbound['Status'] = df_inbound['PO_Status'].fillna('Sent')

        # Calculate price and value in original currency
        df_inbound['Purchase_Price'] = pd.to_numeric(df_inbound['Purchase_Price'], errors='coerce').fillna(0)
        df_inbound['Currency'] = df_inbound['Currency'].fillna('SEK')

        # Total value in original currency = Outstanding_Cases × Purchase_Price
        df_inbound['Total_Outstanding_Value'] = df_inbound['Outstanding_Cases'] * df_inbound['Purchase_Price']

        # Keep SEK value for backward compatibility
        df_inbound['Total_Value_SEK'] = df_inbound['Outstanding_St'] * df_inbound['Pris_st_SEK'].fillna(0)

        # Use Actual_Delivery_Date (EVENT_DATE) directly
        # EVENT_DATE shows: expected date (Sent), partial delivery date (PartlyDelivered), or actual date (FullyDelivered)
        df_inbound['Expected_Arrival'] = df_inbound['Actual_Delivery_Date']

        # Fallback: If EVENT_DATE is missing, calculate Order_Date + Leadtime
        # Convert Leadtime to numeric days first
        leadtime_days = pd.to_numeric(df_inbound['Leadtime'], errors='coerce').fillna(0)
        df_inbound['Expected_Arrival'] = df_inbound['Expected_Arrival'].fillna(
            df_inbound['Order_Date'] + pd.to_timedelta(leadtime_days, unit='D')
        )

        # --- STATUS OVERVIEW ---
        st.subheader("📊 Status Overview")
        col1, col2, col3, col4 = st.columns(4)

        total_po_count = len(df_inbound['PO_Number'].unique())
        on_way = df_inbound[df_inbound['Status'] == 'Sent']
        partial = df_inbound[df_inbound['Status'] == 'PartlyDelivered']
        received_recently = df_inbound[(df_inbound['Status'] == 'FullyDelivered') &
                                       (df_inbound['Actual_Delivery_Date'] >= (today_now - timedelta(days=30)))]

        col1.metric("📦 Total POs", total_po_count)
        col2.metric("🚚 In Transit", len(on_way['PO_Number'].unique()))
        col3.metric("📦 Partially Received", len(partial['PO_Number'].unique()))
        col4.metric("✅ Received (30d)", len(received_recently['PO_Number'].unique()))

        st.divider()

        # --- LIFECYCLE WARNING ---
        if 'Lifecycle_Status' in df_inbound.columns:
            phase_out_in_po = df_inbound[df_inbound['Lifecycle_Status'].isin(['Phase Out', 'Discontinued'])]
            if not phase_out_in_po.empty:
                st.warning(f"⚠️ WARNING: {len(phase_out_in_po)} purchase order lines contain Phase Out or Discontinued products!")

                with st.expander("View Phase Out/Discontinued Items"):
                    warning_cols = ['PO_Number', 'SKU', 'Description', 'Lifecycle_Status']
                    if 'Replaced_By_SKU' in phase_out_in_po.columns:
                        warning_cols.append('Replaced_By_SKU')
                    warning_cols = [c for c in warning_cols if c in phase_out_in_po.columns]
                    st.dataframe(
                        phase_out_in_po[warning_cols],
                        hide_index=True
                    )

        st.divider()

        # --- FILTER ---
        st.subheader("🔍 Filter")
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            search_po = st.text_input("Search PO Number")
            search_sku = st.text_input("Search SKU")

        with col_f2:
            all_suppliers_inbound = sorted([str(x) for x in df_inbound['Supplier'].unique() if str(x) != 'saknas'])
            selected_suppliers = st.multiselect("Supplier", all_suppliers_inbound)

        with col_f3:
            all_statuses_inbound = sorted([str(x) for x in df_inbound['Status'].unique()])
            # Set default to statuses that exist in the data
            default_statuses = [s for s in ['Sent', 'PartlyDelivered'] if s in all_statuses_inbound]
            selected_statuses = st.multiselect("Status", all_statuses_inbound, default=default_statuses)

        # Apply filters
        df_filtered = df_inbound.copy()

        if search_po:
            df_filtered = df_filtered[df_filtered['PO_Number'].astype(str).str.contains(search_po, case=False, na=False)]
        if search_sku:
            df_filtered = df_filtered[df_filtered['SKU'].astype(str).str.contains(search_sku, case=False, na=False)]
        if selected_suppliers:
            df_filtered = df_filtered[df_filtered['Supplier'].isin(selected_suppliers)]
        if selected_statuses:
            df_filtered = df_filtered[df_filtered['Status'].isin(selected_statuses)]

        st.divider()

        # --- TABS WITHIN INBOUND ---
        inbound_tabs = st.tabs(["📋 All POs", "🚚 In Transit", "📦 Partially Received", "✅ Recently Received", "📈 Timeline"])

        with inbound_tabs[0]:
            st.subheader("All Inbound Orders")

            # Summary per currency
            value_by_currency = df_filtered.groupby('Currency')['Total_Outstanding_Value'].sum().reset_index()

            st.subheader("💰 Total Value per Currency")
            cols = st.columns(len(value_by_currency) if len(value_by_currency) > 0 else 1)
            for idx, row in value_by_currency.iterrows():
                if idx < len(cols):
                    cols[idx].metric(f"{row['Currency']}", f"{row['Total_Outstanding_Value']:,.2f}".replace(",", " "))

            # Table
            display_cols = ['PO_Number', 'Line_No', 'SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle_Status', 'Status',
                           'Order_Date', 'Expected_Arrival', 'Confirmed_Cases', 'Actual_Delivered_Cases',
                           'Outstanding_Cases', 'Purchase_Price', 'Currency', 'Total_Outstanding_Value']
            display_cols = [c for c in display_cols if c in df_filtered.columns]

            df_display = df_filtered[display_cols].copy()
            df_display = df_display.sort_values('Expected_Arrival', ascending=True)

            st.dataframe(df_display, hide_index=True, use_container_width=True,
                        column_config={
                            "Order_Date": st.column_config.DateColumn("Order Date", format="YYYY-MM-DD"),
                            "Expected_Arrival": st.column_config.DateColumn("Expected Arrival", format="YYYY-MM-DD"),
                            "Purchase_Price": st.column_config.NumberColumn("Price/Case", format="%.2f"),
                            "Total_Outstanding_Value": st.column_config.NumberColumn("Total Value", format="%.2f")
                        })

            export_button(df_display, "Inbound_All")

        with inbound_tabs[1]:
            st.subheader("🚚 In Transit (Sent)")
            df_sent = df_filtered[df_filtered['Status'] == 'Sent'].copy()

            if df_sent.empty:
                st.info("✅ No orders are currently in transit")
            else:
                # Value per currency
                sent_value_by_currency = df_sent.groupby('Currency')['Total_Outstanding_Value'].sum().reset_index()

                st.subheader("💰 Value per Currency")
                cols = st.columns(len(sent_value_by_currency) if len(sent_value_by_currency) > 0 else 1)
                for idx, row in sent_value_by_currency.iterrows():
                    if idx < len(cols):
                        cols[idx].metric(f"{row['Currency']}", f"{row['Total_Outstanding_Value']:,.2f}".replace(",", " "))

                display_cols = ['PO_Number', 'SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle_Status', 'Order_Date',
                               'Expected_Arrival', 'Confirmed_Cases', 'Outstanding_Cases', 'Purchase_Price', 'Currency', 'Total_Outstanding_Value']
                display_cols = [c for c in display_cols if c in df_sent.columns]

                df_sent_display = df_sent[display_cols].sort_values('Expected_Arrival', ascending=True)

                st.dataframe(df_sent_display, hide_index=True, use_container_width=True,
                            column_config={
                                "Order_Date": st.column_config.DateColumn("Order Date", format="YYYY-MM-DD"),
                                "Expected_Arrival": st.column_config.DateColumn("Expected Arrival", format="YYYY-MM-DD"),
                                "Purchase_Price": st.column_config.NumberColumn("Price/Case", format="%.2f"),
                                "Total_Outstanding_Value": st.column_config.NumberColumn("Total Value", format="%.2f")
                            })

                export_button(df_sent_display, "Inbound_InTransit")

        with inbound_tabs[2]:
            st.subheader("📦 Partially Received (PartlyDelivered)")
            df_partial = df_filtered[df_filtered['Status'] == 'PartlyDelivered'].copy()

            if df_partial.empty:
                st.info("✅ No partially received orders")
            else:
                # Value per currency
                partial_value_by_currency = df_partial.groupby('Currency')['Total_Outstanding_Value'].sum().reset_index()

                st.subheader("💰 Outstanding Value per Currency")
                cols = st.columns(len(partial_value_by_currency) if len(partial_value_by_currency) > 0 else 1)
                for idx, row in partial_value_by_currency.iterrows():
                    if idx < len(cols):
                        cols[idx].metric(f"{row['Currency']}", f"{row['Total_Outstanding_Value']:,.2f}".replace(",", " "))

                st.metric("📊 Number of POs", len(df_partial['PO_Number'].unique()))

                display_cols = ['PO_Number', 'SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle_Status', 'Order_Date',
                               'Confirmed_Cases', 'Actual_Delivered_Cases', 'Outstanding_Cases',
                               'Purchase_Price', 'Currency', 'Total_Outstanding_Value']
                display_cols = [c for c in display_cols if c in df_partial.columns]

                df_partial_display = df_partial[display_cols].copy()

                st.dataframe(df_partial_display, hide_index=True, use_container_width=True,
                            column_config={
                                "Order_Date": st.column_config.DateColumn("Order Date", format="YYYY-MM-DD"),
                                "Purchase_Price": st.column_config.NumberColumn("Price/Case", format="%.2f"),
                                "Total_Outstanding_Value": st.column_config.NumberColumn("Total Value", format="%.2f")
                            })

                export_button(df_partial_display, "Inbound_Partial")

        with inbound_tabs[3]:
            st.subheader("✅ Recently Received (30 days)")
            df_received = df_inbound[(df_inbound['Status'] == 'FullyDelivered') &
                                     (df_inbound['Actual_Delivery_Date'] >= (today_now - timedelta(days=30)))].copy()

            if df_received.empty:
                st.info("No orders have been received in the last 30 days")
            else:
                # Calculate received value per currency
                df_received['Total_Received_Value'] = df_received['Confirmed_Cases'] * df_received['Purchase_Price']
                received_value_by_currency = df_received.groupby('Currency')['Total_Received_Value'].sum().reset_index()

                st.subheader("💰 Received Value per Currency")
                cols = st.columns(len(received_value_by_currency) if len(received_value_by_currency) > 0 else 1)
                for idx, row in received_value_by_currency.iterrows():
                    if idx < len(cols):
                        cols[idx].metric(f"{row['Currency']}", f"{row['Total_Received_Value']:,.2f}".replace(",", " "))

                st.metric("📊 Number of POs", len(df_received['PO_Number'].unique()))

                display_cols = ['PO_Number', 'SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle_Status', 'Order_Date',
                               'Actual_Delivery_Date', 'Confirmed_Cases', 'Actual_Delivered_Cases', 'Purchase_Price', 'Currency']
                display_cols = [c for c in display_cols if c in df_received.columns]

                df_received_display = df_received[display_cols].copy()

                # Calculate total for received orders (use Confirmed_Cases since everything is delivered)
                df_received_display['Total_Value'] = df_received_display['Confirmed_Cases'] * df_received_display['Purchase_Price']

                df_received_display = df_received_display.rename(columns={'Actual_Delivery_Date': 'Received_Date'})
                df_received_display = df_received_display.sort_values('Received_Date', ascending=False)

                st.dataframe(df_received_display, hide_index=True, use_container_width=True,
                            column_config={
                                "Order_Date": st.column_config.DateColumn("Order Date", format="YYYY-MM-DD"),
                                "Received_Date": st.column_config.DateColumn("Received Date", format="YYYY-MM-DD"),
                                "Purchase_Price": st.column_config.NumberColumn("Price/Case", format="%.2f"),
                                "Total_Value": st.column_config.NumberColumn("Total Value", format="%.2f")
                            })

                export_button(df_received_display, "Inbound_Received")

        with inbound_tabs[4]:
            st.subheader("📈 Delivery Timeline")

            # Timeline for expected deliveries
            df_timeline = df_filtered[df_filtered['Status'].isin(['Sent', 'PartlyDelivered'])].copy()

            if df_timeline.empty or df_timeline['Expected_Arrival'].isna().all():
                st.info("No timeline data available for active orders")
            else:
                # Group per week
                df_timeline['Week'] = df_timeline['Expected_Arrival'].dt.to_period('W').astype(str)
                timeline_summary = df_timeline.groupby('Week').agg({
                    'Outstanding_St': 'sum',
                    'Total_Value_SEK': 'sum',
                    'PO_Number': 'nunique'
                }).reset_index()
                timeline_summary = timeline_summary.rename(columns={'PO_Number': 'Number_POs'})
                timeline_summary = timeline_summary.sort_values('Week')

                # Chart
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=timeline_summary['Week'],
                    y=timeline_summary['Outstanding_St'],
                    name='Quantity (pcs)',
                    marker_color='#636EFA'
                ))

                fig.update_layout(
                    title='Expected Deliveries per Week',
                    xaxis_title='Week',
                    yaxis_title='Quantity (pcs)',
                    hovermode='x unified'
                )

                st.plotly_chart(fig, use_container_width=True)

                # Table
                st.dataframe(timeline_summary, hide_index=True, use_container_width=True,
                            column_config={
                                "Total_Value_SEK": st.column_config.NumberColumn("Value (SEK)", format="%.0f kr"),
                                "Outstanding_St": st.column_config.NumberColumn("Quantity (pcs)", format="%d")
                            })

with tabs[3]:
    st.header("Sales per Month (pcs)")
    # Merge with master data, including lifecycle fields if available
    master_cols_for_outbound = ['SKU', 'CC', 'Description', 'Supplier', 'GP_Nummer', 'Status']
    available_master_cols = [c for c in master_cols_for_outbound if c in df_master.columns]
    df_ot = pd.merge(df_sales_all, df_master[available_master_cols].drop_duplicates('SKU'), on='SKU', how='left')

    q_ot = pd.to_numeric(df_ot['QTY_ORIG'], errors='coerce').fillna(0)
    df_ot['Qty_st'] = q_ot * df_ot['CC'].fillna(1)
    df_ot['Månad'] = df_ot['EVENT_DATE'].dt.to_period('M').astype(str)

    # Build pivot index dynamically based on available columns
    pivot_index = ['SKU']
    for col in ['Description', 'Supplier', 'Status']:
        if col in df_ot.columns:
            pivot_index.append(col)

    pivot_ot = apply_filters(df_ot.pivot_table(index=pivot_index, columns='Månad', values='Qty_st', aggfunc='sum').fillna(0).reset_index())
    st.dataframe(pivot_ot, hide_index=True, use_container_width=True)
    export_button(pivot_ot, "Outbound")

with tabs[4]:
    st.header("⚠️ Out of Stock Risk")

    # Calculate risk categories
    df_risk = apply_filters(df_final.copy())

    # Lifecycle filter checkbox
    exclude_phase_out = st.checkbox("Exclude Phase Out/Discontinued from recommendations", value=True,
                                    help="Filter out products that are being phased out or discontinued")

    # Filter out products without consumption
    df_risk = df_risk[df_risk['Snitt_Prog'] > 0].copy()

    # Filter lifecycle status if checkbox selected
    if exclude_phase_out and 'Lifecycle_Status' in df_risk.columns:
        df_risk = df_risk[df_risk['Lifecycle_Status'].isin(['Active', 'Phase In'])].copy()

    # Calculate risk category
    def calculate_risk_category(days):
        if days < 7:
            return '🔴 Critical (<7d)'
        elif days < 10:
            return '🟡 High (<10d)'
        elif days < 30:
            return '🟠 Medium (<30d)'
        else:
            return '🟢 Low (>30d)'

    df_risk['Risk_Category'] = df_risk['Days_on_Stock'].apply(calculate_risk_category)

    # Calculate recommended order
    def calculate_order_recommendation(row):
        # Target: Have 30 days of stock
        target_stock = row['Snitt_Prog'] * 30
        current_stock = row['Saldo_MAIN']
        incoming_po = row['Rest_st'] if pd.notna(row['Rest_st']) else 0

        # Calculate gap
        total_available = current_stock + incoming_po
        gap = target_stock - total_available

        if gap > 0:
            # Convert to cases and round up
            cases_needed = np.ceil(gap / row['Case_config']) if row['Case_config'] > 0 else 0
            return max(0, cases_needed)
        return 0

    df_risk['Rekommenderad_Order_Cases'] = df_risk.apply(calculate_order_recommendation, axis=1)
    df_risk['Rekommenderad_Order_St'] = df_risk['Rekommenderad_Order_Cases'] * df_risk['Case_config']

    # Calculate when PO is expected vs when stock runs out
    df_risk['Stock_Out_Date'] = df_risk['Slutdatum']

    # Convert PO_Datum to date for comparison
    df_risk['PO_Datum_Date'] = pd.to_datetime(df_risk['PO_Datum']).dt.date

    df_risk['PO_Arrives_Before_Stockout'] = df_risk.apply(
        lambda row: 'Yes' if pd.notna(row['PO_Datum_Date']) and pd.notna(row['Stock_Out_Date']) and row['PO_Datum_Date'] < row['Stock_Out_Date']
        else ('No' if pd.notna(row['PO_Datum_Date']) and pd.notna(row['Stock_Out_Date']) and row['PO_Datum_Date'] >= row['Stock_Out_Date']
        else 'No PO'), axis=1
    )

    # --- STATUS OVERVIEW ---
    st.subheader("📊 Risk Overview")
    col1, col2, col3, col4 = st.columns(4)

    critical = df_risk[df_risk['Days_on_Stock'] < 7]
    high = df_risk[(df_risk['Days_on_Stock'] >= 7) & (df_risk['Days_on_Stock'] < 10)]
    medium = df_risk[(df_risk['Days_on_Stock'] >= 10) & (df_risk['Days_on_Stock'] < 30)]
    low = df_risk[df_risk['Days_on_Stock'] >= 30]

    col1.metric("🔴 Critical Risk", f"{len(critical)} SKU")
    col2.metric("🟡 High Risk", f"{len(high)} SKU")
    col3.metric("🟠 Medium Risk", f"{len(medium)} SKU")
    col4.metric("🟢 Low Risk", f"{len(low)} SKU")

    st.divider()

    # ABC Distribution within risk
    st.subheader("📈 Risk per ABC Class")
    risk_abc = df_risk.groupby(['Risk_Category', 'ABC']).size().reset_index(name='Count')
    fig_abc = px.bar(risk_abc, x='Risk_Category', y='Count', color='ABC',
                     barmode='group',
                     color_discrete_map=ABC_COLORS,
                     title='Number of SKUs per Risk Category and ABC Class')
    st.plotly_chart(fig_abc, use_container_width=True)

    st.divider()

    # --- FILTER ---
    st.subheader("🔍 Filter")
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)

    with col_f1:
        risk_filter = st.multiselect("Risk Category",
                                     ['🔴 Critical (<7d)', '🟡 High (<10d)', '🟠 Medium (<30d)', '🟢 Low (>30d)'],
                                     default=['🔴 Critical (<7d)', '🟡 High (<10d)'])

    with col_f2:
        abc_filter = st.multiselect("ABC Class", ['A', 'B', 'C'], default=['A', 'B'])

    with col_f3:
        po_status_filter = st.multiselect("PO Status",
                                         ['No PO', 'No', 'Yes'],
                                         default=['No PO', 'No'])

    with col_f4:
        all_statuses_risk = sorted([str(x) for x in df_risk['Status'].unique()])
        default_status = ['Active'] if 'Active' in all_statuses_risk else []
        status_filter = st.multiselect("Status", all_statuses_risk, default=default_status)

    # Apply filters
    df_risk_filtered = df_risk.copy()
    if risk_filter:
        df_risk_filtered = df_risk_filtered[df_risk_filtered['Risk_Category'].isin(risk_filter)]
    if abc_filter:
        df_risk_filtered = df_risk_filtered[df_risk_filtered['ABC'].isin(abc_filter)]
    if po_status_filter:
        df_risk_filtered = df_risk_filtered[df_risk_filtered['PO_Arrives_Before_Stockout'].isin(po_status_filter)]
    if status_filter:
        df_risk_filtered = df_risk_filtered[df_risk_filtered['Status'].isin(status_filter)]

    st.divider()

    # --- TABS WITHIN STOCK RISK ---
    risk_tabs = st.tabs(["📋 All Risks", "🛒 Order Recommendations", "⏰ Timeline"])

    with risk_tabs[0]:
        st.subheader("All Products with Risk")

        # Sort by Days_on_Stock (least first)
        df_risk_display = df_risk_filtered.sort_values('Days_on_Stock', ascending=True)

        # Display columns
        display_cols = ['SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle_Status', 'ABC', 'Risk_Category',
                       'Days_on_Stock', 'Stock_Out_Date', 'Saldo_MAIN', 'Snitt_Prog',
                       'Rest_st', 'PO_Datum', 'PO_Arrives_Before_Stockout']
        display_cols = [c for c in display_cols if c in df_risk_display.columns]

        st.dataframe(df_risk_display[display_cols], hide_index=True, use_container_width=True,
                    column_config={
                        "Days_on_Stock": st.column_config.NumberColumn("Days Left", format="%.1f"),
                        "Stock_Out_Date": st.column_config.DateColumn("Out-of-Stock Date", format="YYYY-MM-DD"),
                        "Snitt_Prog": st.column_config.NumberColumn("Daily Consumption", format="%.1f"),
                        "PO_Datum": st.column_config.DateColumn("PO Arrival", format="YYYY-MM-DD")
                    })

        export_button(df_risk_display[display_cols], "Stock_Risk_All")

    with risk_tabs[1]:
        st.subheader("🛒 Order Recommendations")

        # Show only products that need to be ordered
        df_order_rec = df_risk_filtered[df_risk_filtered['Rekommenderad_Order_Cases'] > 0].copy()
        df_order_rec = df_order_rec.sort_values('Days_on_Stock', ascending=True)

        if df_order_rec.empty:
            st.info("✅ No orders needed for the selected filters")
        else:
            st.write(f"**{len(df_order_rec)} products need to be ordered**")

            # Summary
            total_cases = df_order_rec['Rekommenderad_Order_Cases'].sum()
            total_st = df_order_rec['Rekommenderad_Order_St'].sum()

            col1, col2 = st.columns(2)
            col1.metric("Total Cases to Order", f"{int(total_cases):,}".replace(",", " "))
            col2.metric("Total Pieces to Order", f"{int(total_st):,}".replace(",", " "))

            st.divider()

            # Table
            display_cols = ['SKU', 'GP_Nummer', 'Description', 'Supplier', 'Lifecycle_Status', 'ABC', 'Risk_Category',
                           'Days_on_Stock', 'Saldo_MAIN', 'Rest_st', 'Snitt_Prog',
                           'Rekommenderad_Order_Cases', 'Rekommenderad_Order_St', 'Leadtime']
            display_cols = [c for c in display_cols if c in df_order_rec.columns]

            st.dataframe(df_order_rec[display_cols], hide_index=True, use_container_width=True,
                        column_config={
                            "Days_on_Stock": st.column_config.NumberColumn("Days Left", format="%.1f"),
                            "Snitt_Prog": st.column_config.NumberColumn("Daily Consumption", format="%.1f"),
                            "Rekommenderad_Order_Cases": st.column_config.NumberColumn("Order (Cases)", format="%d"),
                            "Rekommenderad_Order_St": st.column_config.NumberColumn("Order (Pcs)", format="%d")
                        })

            export_button(df_order_rec[display_cols], "Order_Recommendations")

            # Group per supplier for easy ordering
            st.subheader("📦 Per Supplier")
            supplier_summary = df_order_rec.groupby('Supplier').agg({
                'SKU': 'count',
                'Rekommenderad_Order_Cases': 'sum',
                'Rekommenderad_Order_St': 'sum'
            }).reset_index()
            supplier_summary.columns = ['Supplier', 'Number of SKU', 'Total Cases', 'Total Pieces']

            st.dataframe(supplier_summary, hide_index=True, use_container_width=True)

    with risk_tabs[2]:
        st.subheader("⏰ Stock-Out Timeline")

        # Group per week when products run out
        df_timeline = df_risk_filtered[pd.notna(df_risk_filtered['Stock_Out_Date'])].copy()

        if df_timeline.empty:
            st.info("No timeline data available")
        else:
            df_timeline['Stock_Out_Date'] = pd.to_datetime(df_timeline['Stock_Out_Date'])
            df_timeline['Week'] = df_timeline['Stock_Out_Date'].dt.to_period('W').astype(str)

            timeline_summary = df_timeline.groupby(['Week', 'ABC']).size().reset_index(name='Count')
            timeline_summary = timeline_summary.sort_values('Week')

            # Chart
            fig_timeline = px.bar(timeline_summary, x='Week', y='Count', color='ABC',
                                 color_discrete_map=ABC_COLORS,
                                 title='Number of SKUs Running Out per Week',
                                 labels={'Count': 'Number of SKU', 'Week': 'Week'})
            st.plotly_chart(fig_timeline, use_container_width=True)

            # Table with details per week
            st.subheader("Details per Week")
            week_details = df_timeline.groupby('Week').agg({
                'SKU': 'count',
                'ABC': lambda x: f"A:{sum(x=='A')}, B:{sum(x=='B')}, C:{sum(x=='C')}"
            }).reset_index()
            week_details.columns = ['Week', 'Number of SKU', 'ABC Distribution']

            st.dataframe(week_details, hide_index=True, use_container_width=True)

with tabs[5]:
    st.header("Inventory Analysis & Forecast (MAIN)")
    f_an = apply_filters(df_final)
    # Remove same columns as in Stock Balance
    cols_analys = ['SKU', 'Description', 'Status', 'ABC', 'Days_on_Stock', 'Slutdatum', 'Saldo_MAIN', 'Pallets', 'Snitt_30d', 'Actual_30d', 'Snitt_Prog', 'MAE', 'MAPE', 'Kommentar']
    f_an_filtered = f_an[[c for c in cols_analys if c in f_an.columns]]
    # Round all numeric columns to integers
    for col in ['Snitt_30d', 'Actual_30d', 'Snitt_Prog', 'MAE', 'MAPE']:
        if col in f_an_filtered.columns:
            f_an_filtered[col] = f_an_filtered[col].round(0).astype(int)
    edited = st.data_editor(f_an_filtered, use_container_width=True, hide_index=True, key="an_edit",
                           column_config={
                               "Snitt_30d": st.column_config.NumberColumn("Snitt_30d", format="%d"),
                               "Actual_30d": st.column_config.NumberColumn("Actual_30d", format="%d"),
                               "Snitt_Prog": st.column_config.NumberColumn("Snitt_Prog", format="%d"),
                               "MAE": st.column_config.NumberColumn("MAE", format="%d"),
                               "MAPE": st.column_config.NumberColumn("MAPE", format="%d %%")
                           })
    if st.button("💾 Save Comments"):
        if save_comments(edited): st.success("Saved!"); st.cache_data.clear()
    export_button(edited, "Analysis")

with tabs[6]:
    st.header("Detailed Customer Search")
    if 'CUSTOMER' in df_trans.columns:
        customers = sorted([str(x) for x in df_trans['CUSTOMER'].unique() if str(x) != 'saknas' and x is not None])
        sel_cust = st.multiselect("Select Customer(s)", customers)
        df_c = df_trans[df_trans['FLOW_TYPE'] == 'SALES'].copy()
        if sel_cust: df_c = df_c[df_c['CUSTOMER'].isin(sel_cust)]
        df_c = pd.merge(df_c, df_master[['SKU', 'Description', 'CC', 'Supplier', 'Status']], on='SKU', how='left')
        df_c['Qty_st'] = pd.to_numeric(df_c['QTY_ORIG'], errors='coerce').fillna(0) * df_c['CC'].fillna(1)
        st.dataframe(apply_filters(df_c), hide_index=True, use_container_width=True)
    else:
        st.warning("⚠️ Customer data is missing in transaction data. CUSTOMER column not found.")

with tabs[7]:
    st.header("🔄 Product Lifecycle Management")

    # Section 1: Active Transitions Dashboard
    st.subheader("📊 Active Transitions")

    active_trans = df_transitions[df_transitions['Status'] == 'Active']

    if active_trans.empty:
        st.info("No active transitions")
    else:
        # Enrich with current stock data
        for idx, trans in active_trans.iterrows():
            old_stock = df_final[df_final['SKU'] == trans['Old_SKU']]['Saldo_MAIN'].iloc[0] if trans['Old_SKU'] in df_final['SKU'].values else 0

            col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

            with col1:
                st.write(f"**GP:** {trans['GP_Nummer']}")
                st.write(f"Old: {trans['Old_SKU']} → New: {trans['New_SKU']}")

            with col2:
                if trans['Transition_Type'] == 'Hard':
                    days_until = (pd.to_datetime(trans['Hard_Date']) - pd.Timestamp.now()).days
                    st.write(f"🗓️ Hard Transition")
                    st.write(f"Date: {trans['Hard_Date'].strftime('%Y-%m-%d')}")
                    st.write(f"⏱️ {days_until} days remaining")
                else:
                    st.write(f"🔄 Soft Transition")
                    st.write(f"Stock: {old_stock} cases")

            with col3:
                st.write(f"Created: {trans['Created_Date'].strftime('%Y-%m-%d')}")

            with col4:
                if st.button(f"Complete", key=f"complete_{trans['Transition_ID']}"):
                    # Mark as completed
                    df_transitions.loc[df_transitions['Transition_ID'] == trans['Transition_ID'], 'Status'] = 'Completed'
                    df_transitions.loc[df_transitions['Transition_ID'] == trans['Transition_ID'], 'Completed_Date'] = pd.Timestamp.now()

                    # Update product statuses
                    df_master.loc[df_master['SKU'] == trans['Old_SKU'], 'Lifecycle_Status'] = 'Discontinued'
                    df_master.loc[df_master['SKU'] == trans['New_SKU'], 'Lifecycle_Status'] = 'Active'

                    # Save
                    df_transitions.to_csv('transitions.csv', index=False)
                    df_master.to_parquet(MASTER_FILE)

                    st.success(f"Transition {trans['Transition_ID']} completed!")
                    st.rerun()

            st.divider()

    st.write("")
    st.write("")

    # Section 2: Create New Transition
    st.subheader("➕ Create New Transition")

    with st.form("create_transition_form"):
        col1, col2 = st.columns(2)

        with col1:
            # GP Number selector
            all_gp = sorted(df_master['GP_Nummer'].unique())
            selected_gp = st.selectbox("GP Number", [''] + all_gp, help="Select GP Number to filter SKUs")

            # Old SKU (filtered by GP if selected)
            if selected_gp:
                old_sku_options = df_master[
                    (df_master['GP_Nummer'] == selected_gp) &
                    (df_master['Lifecycle_Status'] == 'Active')
                ]['SKU'].tolist()
            else:
                old_sku_options = df_master[df_master['Lifecycle_Status'] == 'Active']['SKU'].tolist()

            old_sku = st.selectbox("Old SKU (to phase out)", [''] + old_sku_options)

            # Transition type
            transition_type = st.radio("Transition Type", ['Soft', 'Hard'],
                                     help="Soft: Use all old stock first. Hard: Switch on specific date")

        with col2:
            # New SKU (filtered by GP if selected)
            if selected_gp:
                new_sku_options = df_master[
                    (df_master['GP_Nummer'] == selected_gp) &
                    (df_master['Lifecycle_Status'].isin(['Active', 'Phase In']))
                ]['SKU'].tolist()
            else:
                new_sku_options = df_master[
                    df_master['Lifecycle_Status'].isin(['Active', 'Phase In'])
                ]['SKU'].tolist()

            new_sku = st.selectbox("New SKU (replacement)", [''] + new_sku_options)

            # Hard date (only if Hard selected)
            if transition_type == 'Hard':
                hard_date = st.date_input("Transition Date",
                                         min_value=datetime.now().date() + timedelta(days=1))
            else:
                hard_date = None

            # Notes
            notes = st.text_area("Notes (optional)")

        # Submit button
        submitted = st.form_submit_button("Create Transition")

        if submitted:
            if not old_sku or not new_sku:
                st.error("Please select both Old SKU and New SKU")
            else:
                result = create_transition(df_master, df_transitions, old_sku, new_sku,
                                         transition_type, hard_date, notes)

                if result['success']:
                    st.success(f"✅ Transition created! ID: {result['transition_id']}")
                    st.rerun()
                else:
                    st.error("❌ Transition creation failed:")
                    for error in result['errors']:
                        st.error(f"  • {error}")

    st.write("")
    st.write("")

    # Section 3: Transition History
    st.subheader("📜 Transition History")

    completed_trans = df_transitions[df_transitions['Status'] == 'Completed'].sort_values('Completed_Date', ascending=False)

    if completed_trans.empty:
        st.info("No completed transitions")
    else:
        st.dataframe(
            completed_trans[['Transition_ID', 'GP_Nummer', 'Old_SKU', 'New_SKU',
                           'Transition_Type', 'Created_Date', 'Completed_Date']],
            hide_index=True
        )

with tabs[8]:  # NPI tab
    st.header("🆕 New Product Introduction (NPI)")

    # SECTION 1: Pipeline Status Metrics
    st.subheader("📊 NPI Pipeline Status")
    status_counts = get_npi_status_counts(df_npi)

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Draft", status_counts['Draft'], help="Draft entries")
    with col2:
        st.metric("Submitted", status_counts['Submitted'], help="Awaiting approval")
    with col3:
        st.metric("Approved", status_counts['Approved'], help="Ready to launch")
    with col4:
        st.metric("Launched", status_counts['Launched'], help="Active products")
    with col5:
        st.metric("Cancelled", status_counts['Cancelled'], help="Rejected/cancelled")

    st.divider()

    # SECTION 2: Active NPI Submissions
    st.subheader("📋 Active NPI Submissions")

    # Filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        status_filter = st.multiselect("Status",
            ['Draft', 'Submitted', 'Approved', 'Launched', 'Cancelled'],
            default=['Draft', 'Submitted', 'Approved'],
            key='npi_status_filter')
    with col_f2:
        if not df_npi.empty and 'Master_Vendor_Name' in df_npi.columns:
            supplier_options = ['All'] + sorted(df_npi['Master_Vendor_Name'].dropna().unique().tolist())
        else:
            supplier_options = ['All']
        supplier_filter = st.selectbox("Supplier", supplier_options, key='npi_supplier_filter')
    with col_f3:
        search_term = st.text_input("Search", placeholder="Product description or article #", key='npi_search')

    # Filter dataframe
    df_npi_filtered = df_npi.copy()
    if not df_npi_filtered.empty:
        if status_filter and 'Status' in df_npi_filtered.columns:
            df_npi_filtered = df_npi_filtered[df_npi_filtered['Status'].isin(status_filter)]
        if supplier_filter != 'All' and 'Master_Vendor_Name' in df_npi_filtered.columns:
            df_npi_filtered = df_npi_filtered[df_npi_filtered['Master_Vendor_Name'] == supplier_filter]
        if search_term:
            df_npi_filtered = df_npi_filtered[
                df_npi_filtered['Product_Description'].str.contains(search_term, case=False, na=False) |
                df_npi_filtered['Vendor_Article_Number'].str.contains(search_term, case=False, na=False)
            ]

    # Display table
    if df_npi_filtered.empty:
        st.info("No NPI entries match the filters")
    else:
        display_cols = ['NPI_ID', 'Product_Description', 'Master_Vendor_Name',
                       'SAS_GP4_Number', 'Status', 'Created_Date']

        st.dataframe(
            df_npi_filtered[display_cols].sort_values('Created_Date', ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                'NPI_ID': 'NPI ID',
                'Product_Description': 'Product',
                'Master_Vendor_Name': 'Supplier',
                'SAS_GP4_Number': 'GP4 #',
                'Status': st.column_config.TextColumn('Status'),
                'Created_Date': st.column_config.DateColumn('Created', format='YYYY-MM-DD')
            }
        )

        # Action buttons for selected NPI
        if not df_npi_filtered.empty and 'NPI_ID' in df_npi_filtered.columns:
            st.write("**Actions:**")
            selected_npi_id = st.selectbox("Select NPI",
                df_npi_filtered['NPI_ID'].tolist(),
                key='action_npi_select')

            if selected_npi_id:
                selected_npi = df_npi[df_npi['NPI_ID'] == selected_npi_id].iloc[0]

                col_a1, col_a2, col_a3, col_a4 = st.columns(4)

                with col_a1:
                    if selected_npi['Status'] == 'Draft':
                        if st.button("📤 Submit for Review"):
                            result = submit_npi(df_npi, selected_npi_id)
                            if result['success']:
                                st.success(f"NPI {selected_npi_id} submitted!")
                                st.rerun()
                            else:
                                for error in result.get('errors', []):
                                    st.error(error)

                with col_a2:
                    if selected_npi['Status'] == 'Submitted':
                        if st.button("✅ Approve"):
                            result = approve_npi(df_npi, selected_npi_id, approved_by='System')
                            if result['success']:
                                st.success(f"NPI {selected_npi_id} approved!")
                                st.rerun()
                            else:
                                for error in result.get('errors', []):
                                    st.error(error)

                with col_a3:
                    if selected_npi['Status'] == 'Approved':
                        with st.form("launch_form"):
                            new_sku = st.text_input("New SKU",
                                value=f"SKU-{selected_npi['Vendor_Article_Number']}")
                            launch_submitted = st.form_submit_button("🚀 Launch Product")

                            if launch_submitted:
                                result = launch_npi_to_master(df_master, df_npi,
                                    selected_npi_id, new_sku)
                                if result['success']:
                                    st.success(f"Product launched! SKU: {result['sku']}")
                                    st.rerun()
                                else:
                                    st.error(result.get('error', 'Launch failed'))

                with col_a4:
                    if selected_npi['Status'] not in ['Launched', 'Cancelled']:
                        with st.popover("❌ Cancel"):
                            reason = st.text_area("Rejection Reason",
                                placeholder="Why is this NPI being cancelled?")
                            if st.button("Confirm Cancel"):
                                result = cancel_npi(df_npi, selected_npi_id, reason)
                                if result['success']:
                                    st.success("NPI cancelled")
                                    st.rerun()
                                else:
                                    st.error(result.get('error'))

    st.divider()

    # SECTION 3: Create New NPI Entry (Form)
    with st.expander("➕ Create New NPI Entry (Single Product Form)", expanded=False):
        with st.form("create_npi_form"):
            st.subheader("Basic Information")

            col1, col2, col3 = st.columns(3)
            with col1:
                product_desc = st.text_input("Product Description*",
                    max_chars=49, help="Max 49 characters")
                vendor_article = st.text_input("Vendor Article Number*")
                master_vendor = st.text_input("Master Vendor Name*")

            with col2:
                sas_gp4 = st.text_input("SAS GP4 Number")
                sas_category = st.selectbox("SAS Product Category",
                    ['', 'Food', 'Beverage', 'Retail', 'Other'])
                sas_owner = st.text_input("SAS Product Owner")

            with col3:
                case_config = st.number_input("Case Configuration (pcs/case)*",
                    min_value=1, step=1, value=1)
                storage_cond = st.selectbox("Storage Condition*",
                    ['', 'Ambient', 'Chilled', 'Frozen'])
                lead_time_days = st.number_input("Lead Time (days)",
                    min_value=0, step=1, value=0)

            st.subheader("Pricing & Regulatory (minimum required)")
            col1, col2, col3 = st.columns(3)
            with col1:
                price_case = st.number_input("Purchase Price/Case", min_value=0.0, format="%.2f")
                currency = st.selectbox("Currency", ['', 'EUR', 'USD', 'SEK', 'DKK', 'NOK', 'GBP'])
            with col2:
                duty_status = st.selectbox("Duty Status", ['', 'T1 - Duty Unpaid', 'T2 - Duty Paid'])
                country_origin = st.text_input("Country of Origin (2-digit ISO)", max_chars=2)
            with col3:
                notes = st.text_area("Notes (optional)")

            col_sub1, col_sub2 = st.columns(2)
            with col_sub1:
                submit_draft = st.form_submit_button("💾 Save as Draft")
            with col_sub2:
                submit_review = st.form_submit_button("📤 Submit for Review")

            if submit_draft or submit_review:
                npi_data = {
                    'Product_Description': product_desc,
                    'Vendor_Article_Number': vendor_article,
                    'Master_Vendor_Name': master_vendor,
                    'SAS_GP4_Number': sas_gp4,
                    'SAS_Product_Category': sas_category,
                    'SAS_Product_Owner': sas_owner,
                    'Case_Configuration': case_config,
                    'Storage_Condition': storage_cond,
                    'Lead_Time_Days': lead_time_days,
                    'Purchase_Price_Case': price_case,
                    'Purchase_Price_Currency': currency,
                    'Duty_Status': duty_status,
                    'Country_Of_Origin': country_origin,
                    'Notes': notes
                }

                # Create NPI
                result = create_npi_entry(df_npi, npi_data)

                if result['success']:
                    npi_id = result['npi_id']

                    # If submit for review, do that too
                    if submit_review:
                        submit_result = submit_npi(df_npi, npi_id)
                        if submit_result['success']:
                            st.success(f"✅ NPI {npi_id} created and submitted!")
                        else:
                            st.warning(f"NPI {npi_id} created as Draft (submission failed)")
                            for error in submit_result.get('errors', []):
                                st.error(error)
                    else:
                        st.success(f"✅ NPI {npi_id} saved as Draft!")

                    # Show warnings
                    for warning in result.get('warnings', []):
                        st.warning(warning)

                    st.rerun()
                else:
                    st.error("❌ NPI creation failed:")
                    for error in result.get('errors', []):
                        st.error(f"  • {error}")

    st.divider()

    # SECTION 4: NPI History
    st.subheader("📜 NPI History (Launched Products)")

    launched_npis = df_npi[df_npi['Status'] == 'Launched'].sort_values('Launched_Date', ascending=False) if not df_npi.empty else pd.DataFrame()

    if launched_npis.empty:
        st.info("No launched NPIs yet")
    else:
        st.dataframe(
            launched_npis[['NPI_ID', 'Product_Description', 'Master_Vendor_Name',
                          'SAS_GP4_Number', 'Launched_SKU', 'Launched_Date']],
            use_container_width=True,
            hide_index=True,
            column_config={
                'NPI_ID': 'NPI ID',
                'Product_Description': 'Product',
                'Master_Vendor_Name': 'Supplier',
                'SAS_GP4_Number': 'GP4 #',
                'Launched_SKU': 'SKU',
                'Launched_Date': st.column_config.DateColumn('Launched', format='YYYY-MM-DD')
            }
        )

with tabs[9]:
    st.header("⚙️ Settings")
    st.markdown("Here you can adjust the app settings. **Note:** Changes are only saved for this session.")

    st.divider()

    # Currency rates
    st.subheader("💱 Currency Rates (SEK)")
    st.caption("Adjusts price conversion to SEK. Current values:")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("EUR", f"{CURRENCY_RATES['EUR']:.2f}")
        st.metric("DKK", f"{CURRENCY_RATES['DKK']:.2f}")
    with col2:
        st.metric("NOK", f"{CURRENCY_RATES['NOK']:.2f}")
        st.metric("USD", f"{CURRENCY_RATES['USD']:.2f}")
    with col3:
        st.metric("SEK", f"{CURRENCY_RATES['SEK']:.2f}")

    with st.expander("🔧 Change Currency Rates"):
        st.info("To change currency rates permanently, edit CURRENCY_RATES in the code (line 19-25)")
        new_eur = st.number_input("EUR to SEK", value=CURRENCY_RATES['EUR'], min_value=0.0, step=0.1, format="%.2f")
        new_dkk = st.number_input("DKK to SEK", value=CURRENCY_RATES['DKK'], min_value=0.0, step=0.1, format="%.2f")
        new_nok = st.number_input("NOK to SEK", value=CURRENCY_RATES['NOK'], min_value=0.0, step=0.1, format="%.2f")
        new_usd = st.number_input("USD to SEK", value=CURRENCY_RATES['USD'], min_value=0.0, step=0.1, format="%.2f")
        st.warning("⚠️ Note: Changes here do not affect already loaded data. Restart the app to apply new rates.")

    st.divider()

    # Costs
    st.subheader("💰 Costs")
    st.caption("Adjusts cost calculations in the app.")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("3PL Pallet Cost/Month", f"{PALLET_COST_PER_MONTH} SEK")
    with col2:
        st.metric("Total Monthly Cost (Current)", f"{int(df_final['Pallets'].sum() * PALLET_COST_PER_MONTH):,} SEK".replace(",", " "))

    with st.expander("🔧 Change Pallet Cost"):
        st.info("To change permanently, edit PALLET_COST_PER_MONTH in the code (line 28)")
        new_pallet_cost = st.number_input("Cost per Pallet/Month (SEK)", value=PALLET_COST_PER_MONTH, min_value=0, step=10)
        if new_pallet_cost != PALLET_COST_PER_MONTH:
            st.success(f"New monthly cost would be: {int(df_final['Pallets'].sum() * new_pallet_cost):,} SEK".replace(",", " "))

    st.divider()

    # ABC classification
    st.subheader("📊 ABC Classification")
    st.caption("Adjusts thresholds for ABC analysis.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("A-Class Threshold", f"{int(ABC_A_THRESHOLD * 100)}%")
        abc_a_count = len(df_final[df_final['ABC'] == 'A'])
        st.caption(f"{abc_a_count} SKUs")
    with col2:
        st.metric("B-Class Threshold", f"{int(ABC_B_THRESHOLD * 100)}%")
        abc_b_count = len(df_final[df_final['ABC'] == 'B'])
        st.caption(f"{abc_b_count} SKUs")
    with col3:
        st.metric("C-Class (Remaining)", f"{int((1 - ABC_B_THRESHOLD) * 100)}%")
        abc_c_count = len(df_final[df_final['ABC'] == 'C'])
        st.caption(f"{abc_c_count} SKUs")

    with st.expander("🔧 Change ABC Thresholds"):
        st.info("To change permanently, edit ABC_A_THRESHOLD and ABC_B_THRESHOLD in the code (line 40-41)")
        new_a_threshold = st.slider("A-Class Threshold (%)", min_value=50, max_value=95, value=int(ABC_A_THRESHOLD * 100), step=5) / 100
        new_b_threshold = st.slider("B-Class Threshold (%)", min_value=int(new_a_threshold * 100) + 5, max_value=100, value=int(ABC_B_THRESHOLD * 100), step=5) / 100
        st.caption(f"A: 0-{int(new_a_threshold * 100)}%, B: {int(new_a_threshold * 100)}-{int(new_b_threshold * 100)}%, C: {int(new_b_threshold * 100)}-100%")
        st.warning("⚠️ Note: Changes here do not affect already calculated ABC classification. Restart the app to apply new thresholds.")

    st.divider()

    # Hub mappings
    st.subheader("🏢 Hub Mappings")
    st.caption("Shows which hubs exist in the system and their short names.")

    hub_df = pd.DataFrame(list(HUB_MAPPING.items()), columns=['Full Name', 'Short Name'])
    st.dataframe(hub_df, hide_index=True, use_container_width=True)

    with st.expander("🔧 Change Hub Mappings"):
        st.info("To change permanently, edit HUB_MAPPING in the code (line 31-37)")
        st.warning("⚠️ Hub mappings are used in multiple calculations. Changes require app restart.")

    st.divider()

    # File info
    st.subheader("📁 Data Files")
    st.caption("Information about data sources used by the app.")

    file_info = pd.DataFrame({
        'File': [MASTER_FILE, TRANSACTION_FILE, PAX_FILE, COMMENTS_FILE],
        'Type': ['Master & Stock Data', 'Transaction Data', 'Passenger Data', 'Comments'],
        'Status': [
            '✓ Loaded' if os.path.exists(MASTER_FILE) else '✗ Missing',
            '✓ Loaded' if os.path.exists(TRANSACTION_FILE) else '✗ Missing',
            '✓ Loaded' if os.path.exists(PAX_FILE) else '✗ Missing',
            '✓ Exists' if os.path.exists(COMMENTS_FILE) else 'Created when needed'
        ]
    })
    st.dataframe(file_info, hide_index=True, use_container_width=True)

    st.divider()

    # System info
    st.subheader("ℹ️ System Information")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("**App Version:** 17")
        st.caption("**Streamlit Version:** " + st.__version__)
        st.caption(f"**Number of SKUs:** {len(df_master['SKU'].unique())}")
    with col2:
        st.caption(f"**Number of Transactions:** {len(df_trans)}")
        st.caption(f"**Date Range:** {df_trans['EVENT_DATE'].min().date()} - {df_trans['EVENT_DATE'].max().date()}")
        st.caption(f"**Last Update:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")