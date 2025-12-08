import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Fil för att spara data lokalt
DATABAS_FIL = "lager_data_v12.pkl"

class LagerAppV12:
    def __init__(self, root):
        self.root = root
        self.root.title("Inventory Management V12 - Pallet Tracking & Consumption Analysis")
        self.root.geometry("1600x950")

        # --- FÄRGER ---
        self.c_sidebar_bg = "#f5f5f5"
        self.c_sidebar_fg = "black"
        self.c_main_bg = "#ecf0f1"
        self.c_text_main = "black"
        self.c_accent = "#e74c3c"
        self.c_warning = "#e74c3c"
        self.c_ok = "#27ae60"
        self.c_trend_up = "#2ecc71"
        self.c_trend_down = "#e74c3c"
        self.c_trend_stable = "#f39c12"

        # --- DATA ---
        self.df_master = None
        self.df_stock = None
        self.df_outbound = None
        self.df_inbound = None
        self.df_combined = None
        
        self.current_view_df = None
        self.lbl_summary = None 
        self.status_vars = {}
        self.supplier_vars = {}
        
        # NYTT: För consumption
        self.df_weekly = None  # Veckoanalys dataframe
        self.selected_weeks = []  # Valda veckor
        self.available_weeks = []  # Tillgängliga veckor i data
        self.cons_tree = None  # Träd för consumption-vyn

        # --- GUI STRUKTUR ---
        self.sidebar = tk.Frame(root, bg=self.c_sidebar_bg, width=250)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main_area = tk.Frame(root, bg=self.c_main_bg)
        self.main_area.pack(side="right", fill="both", expand=True)

        # --- STYLING ---
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Treeview", background="white", foreground="black", fieldbackground="white", rowheight=25, font=("Arial", 10))
        style.configure("Treeview.Heading", background="#d9d9d9", foreground="black", font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#3498db')])

        # --- STARTA ---
        self.bygg_sidebar()
        self.ladda_sparad_databas()
        self.visa_dashboard()

    def bygg_sidebar(self):
        tk.Label(self.sidebar, text="INVENTORY\nMANAGER", bg=self.c_sidebar_bg, fg=self.c_sidebar_fg, 
             font=("Arial", 20, "bold"), pady=30).pack()

        self.skapa_menyknapp("📊  Dashboard", self.visa_dashboard)
        self.skapa_menyknapp("📦  All Items", lambda: self.visa_lista("all"))
        self.skapa_menyknapp("⚠️  Overstock", lambda: self.visa_lista("overstock"))
        
        btn_ds = tk.Button(self.sidebar, text="💰  Discontinued Stock", command=lambda: self.visa_lista("deadstock"),
                        bg="#ffebee", fg="#c62828", font=("Arial", 11, "bold"), bd=0, anchor="w", padx=20, pady=10)
        btn_ds.pack(fill="x")
        
        # NYTT: Consumption knapp
        btn_cons = tk.Button(self.sidebar, text="📈  Weekly Consumption", command=self.visa_consumption,
                          bg="#e8f4fc", fg="#2980b9", font=("Arial", 11, "bold"), bd=0, anchor="w", padx=20, pady=10)
        btn_cons.pack(fill="x")
        
        tk.Frame(self.sidebar, bg=self.c_sidebar_bg, height=50).pack()
        self.skapa_menyknapp("⚙️  Settings / Load", self.visa_installningar)

    def skapa_menyknapp(self, text, command):
        btn = tk.Button(self.sidebar, text=text, command=command,
                        bg=self.c_sidebar_bg, fg=self.c_sidebar_fg, 
                        font=("Arial", 11), bd=0, activebackground="#e0e0e0", 
                        activeforeground="black", anchor="w", padx=20, pady=10)
        btn.pack(fill="x")

    def rensa_main_area(self):
        for widget in self.main_area.winfo_children():
            widget.destroy()

    # =========================================================================
    # LOGIK & BERÄKNINGAR
    # =========================================================================
    def berakna_data(self, visa_popup=True):
        if self.df_stock is None: return
        try:
            # 1. OUTBOUND & INBOUND
            out_sum = pd.DataFrame(columns=['SK Number', 'Total_Outbound'])
            if self.df_outbound is not None:
                # Detect SKU and quantity columns robustly (case-insensitive)
                sku_col = next((c for c in self.df_outbound.columns if any(k in c.lower() for k in ['sk ', 'sku', 'item', 'article'])), None)
                qty_col = next((c for c in self.df_outbound.columns if any(k in c.lower() for k in ['qty', 'quantity', 'unit', 'units', 'amount'])), None)
                if sku_col and qty_col:
                    df_o = self.df_outbound.copy()
                    # Normalize SKU column name to 'SK Number' if necessary
                    if sku_col != 'SK Number':
                        try:
                            df_o.rename(columns={sku_col: 'SK Number'}, inplace=True)
                        except Exception:
                            pass
                    try:
                        out_sum = df_o.groupby('SK Number')[qty_col].sum().reset_index().rename(columns={qty_col: 'Total_Outbound'})
                    except Exception:
                        out_sum = pd.DataFrame(columns=['SK Number', 'Total_Outbound'])
            in_sum = pd.DataFrame(columns=['SK Number', 'Total_Inbound'])
            if self.df_inbound is not None:
                q = next((c for c in self.df_inbound.columns if 'Qty' in c or 'Quantity' in c), None)
                if q:
                    try:
                        in_sum = self.df_inbound.groupby('SK Number')[q].sum().reset_index().rename(columns={q: 'Total_Inbound'})
                    except Exception:
                        in_sum = pd.DataFrame(columns=['SK Number', 'Total_Inbound'])
            # 2. STANDARDISERA ID
            self.df_master['SK Number'] = self.df_master['SK Number'].astype(str).str.strip()
            self.df_stock['SK Number'] = self.df_stock['SK Number'].astype(str).str.strip()
            out_sum['SK Number'] = out_sum['SK Number'].astype(str).str.strip()
            in_sum['SK Number'] = in_sum['SK Number'].astype(str).str.strip()

            # 3. HANTERA SAKNADE KOLUMNER
            cols_check = {
                'MASTER VEND PURCHASE COST': 0, 'currency convert': 1, 
                'GP Number': "", 'WAREHOUSE VENDOR NAME': 'Unknown', 
                'MASTER VENDOR LEADTIME': 0
            }
            for col, default in cols_check.items():
                if col not in self.df_master.columns: self.df_master[col] = default

            if 'Nr. of pallets' not in self.df_stock.columns: self.df_stock['Nr. of pallets'] = 0

            # 4. MERGE
            master_cols = ['SK Number', 'GP Number', 'ITEM DESCRIPTION', 'ITEM STATUS', 
                           'WAREHOUSE VENDOR NAME', 'MASTER VEND PURCHASE COST', 'currency convert', 'MASTER VENDOR LEADTIME']
            stock_cols = ['SK Number', 'Current Stock', 'Nr. of pallets']

            merged = pd.merge(self.df_master[master_cols], self.df_stock[stock_cols], on='SK Number', how='left')
            merged = pd.merge(merged, out_sum, on='SK Number', how='left')
            merged = pd.merge(merged, in_sum, on='SK Number', how='left')
            
            merged.rename(columns={'WAREHOUSE VENDOR NAME': 'Supplier'}, inplace=True)

            # 5. STÄDA
            fill_zeros = ['Current Stock', 'Total_Outbound', 'Total_Inbound', 'Nr. of pallets', 
                          'MASTER VEND PURCHASE COST', 'currency convert', 'MASTER VENDOR LEADTIME']
            for c in fill_zeros: merged[c] = pd.to_numeric(merged[c], errors='coerce').fillna(0)
            
            merged['ITEM STATUS'] = merged['ITEM STATUS'].fillna('Unknown')
            merged['Supplier'] = merged['Supplier'].fillna('Unknown')
            merged['GP Number'] = merged['GP Number'].fillna('')

            # 6. FINANSIELLT
            merged['Inventory_Value'] = merged['MASTER VEND PURCHASE COST'] * merged['currency convert'] * merged['Current Stock']
            merged['Storage_Cost_Month'] = merged['Nr. of pallets'] * 100

            # 7. STATUS LOGIK
            status_lower = merged['ITEM STATUS'].astype(str).str.lower().str.strip()
            merged['Is_Deadstock'] = (merged['Current Stock'] > 0) & (status_lower == 'discontinued')
            merged['Is_Overstock'] = (merged['Current Stock'] > (merged['Total_Outbound'] * 3)) & (merged['Total_Outbound'] > 0)
            
            self.df_combined = merged
            
            # 8. SKAPA VEKOANALYS OM VI HAR OUTBOUND DATA
            if self.df_outbound is not None:
                self.skapa_veckoanalys()
            
        except Exception as e: 
            if visa_popup: messagebox.showerror("Error", str(e))

    # =========================================================================
    # DASHBOARD
    # =========================================================================
    def visa_dashboard(self):
        self.rensa_main_area()
        tk.Label(self.main_area, text="Financial Overview", font=("Arial", 24, "bold"), 
                 bg=self.c_main_bg, fg=self.c_text_main).pack(anchor="w", padx=30, pady=30)

        if self.df_combined is None:
            tk.Label(self.main_area, text="No data. Go to Settings to load.", bg=self.c_main_bg, fg="red").pack(padx=30)
            return

        dead_df = self.df_combined[self.df_combined['Is_Deadstock']]
        
        dead_count = len(dead_df)
        dead_value = dead_df['Inventory_Value'].sum()
        total_value = self.df_combined['Inventory_Value'].sum()
        
        # NYTT: Summera pallar
        total_pallets = self.df_combined['Nr. of pallets'].sum()

        kpi_frame = tk.Frame(self.main_area, bg=self.c_main_bg)
        kpi_frame.pack(fill="x", padx=20)

        def fmt_sek(val): return f"{val:,.0f} kr".replace(",", " ")

        self.skapa_kpi_kort(kpi_frame, "Total Inventory Value", fmt_sek(total_value), "#3498db")
        self.skapa_kpi_kort(kpi_frame, "Total Pallets", f"{total_pallets:,.1f}", "#9b59b6") # NYTT
        self.skapa_kpi_kort(kpi_frame, "Discontinued Value", fmt_sek(dead_value), "#e74c3c")
        self.skapa_kpi_kort(kpi_frame, "Discontinued Items", f"{dead_count} pcs", "#7f8c8d")

    def skapa_kpi_kort(self, parent, titel, varde, farg):
        card = tk.Frame(parent, bg="white", bd=0, relief="raised")
        card.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        tk.Frame(card, bg=farg, height=5).pack(fill="x")
        tk.Label(card, text=titel, bg="white", fg="#7f8c8d", font=("Arial", 10)).pack(pady=(15,5))
        tk.Label(card, text=varde, bg="white", fg="#2c3e50", font=("Arial", 18, "bold")).pack(pady=(0,20))

    # =========================================================================
    # LIST-VYER
    # =========================================================================
    def visa_lista(self, vy_typ):
        self.rensa_main_area()
        if self.df_combined is None: return

        # Header
        top_panel = tk.Frame(self.main_area, bg=self.c_main_bg, pady=10, padx=20)
        top_panel.pack(fill="x")

        titles = {"all": "All Items (Details)", "overstock": "⚠️ Overstock", "deadstock": "💰 Discontinued Stock"}
        tk.Label(top_panel, text=titles.get(vy_typ, "List"), font=("Arial", 18, "bold"), 
                 bg=self.c_main_bg, fg="black").pack(side="left")

        btn_export = tk.Button(top_panel, text="💾 Export to Excel", command=lambda: self.exportera_lista(vy_typ),
                               bg="#27ae60", fg="white", font=("Arial", 10, "bold"), padx=10)
        btn_export.pack(side="right", padx=10)

        # Filter
        filter_frame = tk.Frame(top_panel, bg=self.c_main_bg)
        filter_frame.pack(side="right")
        
        tk.Label(filter_frame, text="Search:", bg=self.c_main_bg).pack(side="left")
        sv = tk.StringVar()
        sv.trace("w", lambda n, i, m: self.uppdatera_tabell(vy_typ, sv.get()))
        tk.Entry(filter_frame, textvariable=sv, width=15).pack(side="left", padx=5)

        mb_stat = tk.Menubutton(filter_frame, text="Filter Status ⇩", relief="raised", bg="white", fg="black")
        mb_stat.menu = tk.Menu(mb_stat, tearoff=0, fg="black", bg="white")
        mb_stat["menu"] = mb_stat.menu
        mb_stat.pack(side="left", padx=5)
        self.bygg_filter_meny(mb_stat, "ITEM STATUS", self.status_vars, vy_typ, sv)

        # Tabell Area
        table_frame = tk.Frame(self.main_area, bg="white")
        table_frame.pack(fill="both", expand=True, padx=20, pady=(0, 0))

        if vy_typ == "deadstock":
            self.lbl_summary = tk.Label(self.main_area, text="", bg="#c62828", fg="white", 
                                        font=("Arial", 12, "bold"), padx=10, pady=10)
            self.lbl_summary.pack(side="bottom", fill="x")

        # --- KOLUMNER ---
        if vy_typ == "all":
            # NYTT: Pallar inlagt här
            cols = ("SK Number", "Beskrivning", "Supplier", "Lager (Cases)", "Pallar", "Ledtid")
        elif vy_typ == "deadstock":
            cols = ("SK Number", "GP Number", "Beskrivning", "Status", "Lager", "Pallar", "Varuvärde", "Pallhyra/Mån", "Inbound")
        else:
            # NYTT: Pallar inlagt även i overstock
            cols = ("SK Number", "Beskrivning", "Supplier", "Lager", "Pallar", "Varuvärde", "Status")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        
        self.tree.column("SK Number", width=90, anchor="center")
        self.tree.column("Beskrivning", width=300, anchor="w")
        
        if vy_typ == "all":
            self.tree.column("Supplier", width=200, anchor="w")
            self.tree.column("Lager (Cases)", width=80, anchor="center")
            self.tree.column("Pallar", width=70, anchor="center")
            self.tree.column("Ledtid", width=70, anchor="center")
        
        elif vy_typ == "deadstock":
            self.tree.column("Lager", width=70, anchor="center")
            self.tree.column("GP Number", width=90, anchor="center")
            self.tree.column("Status", width=100, anchor="center")
            self.tree.column("Pallar", width=70, anchor="center")
            self.tree.column("Varuvärde", width=100, anchor="e")
            self.tree.column("Pallhyra/Mån", width=100, anchor="e")
            self.tree.column("Inbound", width=80, anchor="center")
        else:
            self.tree.column("Lager", width=70, anchor="center")
            self.tree.column("Pallar", width=70, anchor="center")
            self.tree.column("Supplier", width=150, anchor="w")
            self.tree.column("Varuvärde", width=90, anchor="e")
            self.tree.column("Status", width=90, anchor="center")

        for col in cols:
            self.tree.heading(col, text=col, command=lambda c=col: self.sortera_kolumn(c, False))

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.oppna_detaljvy)

        if vy_typ == "all":
            self.current_view_df = self.df_combined.copy()
        elif vy_typ == "overstock":
            self.current_view_df = self.df_combined[self.df_combined['Is_Overstock']].copy()
        elif vy_typ == "deadstock":
            temp = self.df_combined[self.df_combined['Is_Deadstock']].copy()
            self.current_view_df = temp.sort_values(by='Inventory_Value', ascending=False)

        self.uppdatera_tabell(vy_typ, "")

    def bygg_filter_meny(self, mb, kolumn, var_dict, vy_typ, sv_search):
        menu = mb.menu
        menu.delete(0, "end")
        if kolumn in self.df_combined.columns:
            unika = sorted(self.df_combined[kolumn].astype(str).unique())
            var_dict.clear() 
            if len(unika) > 1:
                menu.add_command(label="-- Reset --", command=lambda: self.aterstall_filter(var_dict, vy_typ, sv_search))
                menu.add_separator()
            for item in unika:
                var = tk.BooleanVar(value=True) 
                var.trace("w", lambda n, i, m: self.uppdatera_tabell(vy_typ, sv_search.get()))
                menu.add_checkbutton(label=item[:25], variable=var, onvalue=True, offvalue=False)
                var_dict[item] = var

    def aterstall_filter(self, var_dict, vy_typ, sv_search):
        for var in var_dict.values(): var.set(True)
        self.uppdatera_tabell(vy_typ, sv_search.get())

    def uppdatera_tabell(self, vy_typ, search_text):
        self.tree.delete(*self.tree.get_children())
        df = self.current_view_df
        if df is None or df.empty: return

        search_text = search_text.lower()
        mask_text = (
            df['SK Number'].astype(str).str.lower().str.contains(search_text, na=False) |
            df['GP Number'].astype(str).str.lower().str.contains(search_text, na=False) |
            df['ITEM DESCRIPTION'].astype(str).str.lower().str.contains(search_text, na=False)
        )

        sel_stat = [s for s, var in self.status_vars.items() if var.get()]
        if sel_stat: mask_stat = df['ITEM STATUS'].astype(str).isin(sel_stat)
        else: mask_stat = True 

        final_df = df[mask_text & mask_stat]

        if vy_typ == "deadstock" and self.lbl_summary is not None:
            sum_val = final_df['Inventory_Value'].sum()
            sum_rent = final_df['Storage_Cost_Month'].sum()
            summary_text = (f"DISCONTINUED SUMMARY  |  Items: {len(final_df)}  |  "
                            f"Total Value: {sum_val:,.0f} kr  |  "
                            f"Total Storage Cost: {sum_rent:,.0f} kr/mo")
            self.lbl_summary.config(text=summary_text.replace(",", " "))

        for _, row in final_df.iterrows():
            sk = row['SK Number']
            desc = row['ITEM DESCRIPTION']
            curr_stock = int(row['Current Stock'])
            pallets = float(row['Nr. of pallets'])
            
            if vy_typ == "all":
                vals = (
                    sk, desc, row['Supplier'], curr_stock, 
                    f"{pallets:.1f}", # Pallar
                    int(row['MASTER VENDOR LEADTIME'])
                )
            elif vy_typ == "deadstock":
                val = f"{row['Inventory_Value']:,.0f} kr".replace(",", " ")
                storage = f"{row['Storage_Cost_Month']:,.0f} kr".replace(",", " ")
                vals = (
                    sk, row['GP Number'], desc, row['ITEM STATUS'],
                    curr_stock, f"{pallets:.1f}", val, storage, int(row['Total_Inbound'])
                )
            else:
                stat = "OK"
                if row['Is_Overstock']: stat = "OVERSTOCK"
                elif row['Is_Deadstock']: stat = "DEADSTOCK"
                val = f"{row['Inventory_Value']:,.0f} kr".replace(",", " ")
                vals = (
                    sk, desc, row['Supplier'], curr_stock, f"{pallets:.1f}", 
                    val, stat
                )
                
            self.tree.insert("", "end", values=vals)

    def exportera_lista(self, vy_typ):
        if self.current_view_df is None or self.current_view_df.empty: return
        filnamn = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if filnamn:
            try:
                # Export only matching columns from the dataframe
                # Always include core columns if they exist
                core_cols = ['SK Number', 'GP Number', 'ITEM DESCRIPTION', 'ITEM STATUS', 'Current Stock', 'Nr. of pallets', 'Total_Outbound']
                ex = [c for c in core_cols if c in self.current_view_df.columns]
                
                # Export the filtered dataframe
                self.current_view_df[ex].to_excel(filnamn, index=False)
                messagebox.showinfo("Success", f"Exported to {filnamn}")
            except Exception as e: messagebox.showerror("Error", str(e))

    def oppna_detaljvy(self, event):
        selection = self.tree.selection()
        if not selection: return
        sku = self.tree.item(selection[0])['values'][0]
        try: row = self.df_combined[self.df_combined['SK Number'].astype(str) == str(sku)].iloc[0]
        except: return

        popup = tk.Toplevel(self.root)
        popup.title(f"Details: {sku}")
        popup.geometry("600x500")
        
        tk.Label(popup, text=row['ITEM DESCRIPTION'], font=("Arial", 14, "bold")).pack(pady=10)
        tk.Label(popup, text=f"GP: {row['GP Number']} | Status: {row['ITEM STATUS']}", font=("Arial", 10)).pack()
        
        f = tk.Frame(popup, padx=20)
        f.pack(fill="both", pady=20)
        
        def r(l, v):
            fr = tk.Frame(f); fr.pack(fill="x")
            tk.Label(fr, text=l, width=25, anchor="w").pack(side="left")
            tk.Label(fr, text=v, font=("Arial", 10, "bold")).pack(side="left")

        r("Inventory Value:", f"{row['Inventory_Value']:,.0f} kr")
        r("Monthly Storage:", f"{row['Storage_Cost_Month']:,.0f} kr")
        r("Pallets:", f"{row['Nr. of pallets']}")
        r("Lead Time:", f"{int(row['MASTER VENDOR LEADTIME'])} days")
        r("Stock:", f"{int(row['Current Stock'])}")
        r("Supplier:", f"{row['Supplier']}")
        
        if row['Is_Deadstock']:
            tk.Label(popup, text="DISCONTINUED / DEADSTOCK", bg="#c62828", fg="white", font=("Arial", 12, "bold"), pady=5).pack(pady=20)

    # =========================================================================
    # NYTT: CONSUMPTION FLIK
    # =========================================================================
    def visa_consumption(self):
        self.rensa_main_area()
        
        if self.df_combined is None or self.df_outbound is None:
            tk.Label(self.main_area, text="No data. Go to Settings to load files.", 
                     bg=self.c_main_bg, fg="red", font=("Arial", 14)).pack(pady=50)
            return

        # 1. HEADER MED VEKKOVÄLJARE
        header_frame = tk.Frame(self.main_area, bg=self.c_main_bg, pady=20, padx=30)
        header_frame.pack(fill="x")
        
        tk.Label(header_frame, text="📈 Weekly Consumption Analysis", 
                 font=("Arial", 24, "bold"), bg=self.c_main_bg, fg=self.c_text_main).pack(side="left")
        
        # Kontrollpanel till höger
        control_frame = tk.Frame(header_frame, bg=self.c_main_bg)
        control_frame.pack(side="right")
        
        # Veckoväljare
        tk.Label(control_frame, text="Select Weeks:", bg=self.c_main_bg, fg="black").pack(side="left", padx=5)
        
        # Skapa veckoanalys om inte redan gjort
        if self.df_weekly is None:
            self.skapa_veckoanalys()
        
        week_var = tk.StringVar()
        week_combo = ttk.Combobox(control_frame, textvariable=week_var, width=15, 
                                   values=["Last 4 weeks", "Last 8 weeks", "Last 12 weeks", "All available weeks"])
        week_combo.pack(side="left", padx=5)
        week_combo.set("Last 4 weeks")
        week_combo.bind("<<ComboboxSelected>>", lambda e: self.uppdatera_veckovalg(week_var.get()))
        
        # Knapp för att uppdatera
        btn_update = tk.Button(control_frame, text="🔄 Update", command=lambda: self.uppdatera_consumption_vy(week_var.get()),
                               bg="#3498db", fg="white", font=("Arial", 10, "bold"))
        btn_update.pack(side="left", padx=10)
        
        # 2. KPI PANEL
        kpi_frame = tk.Frame(self.main_area, bg=self.c_main_bg, padx=30, pady=10)
        kpi_frame.pack(fill="x")
        
        # Beräkna KPI:er för phase out artiklar med lager
        phase_out_df = self.df_combined[
            (self.df_combined['ITEM STATUS'].str.lower().str.contains('phase out|discontinued')) & 
            (self.df_combined['Current Stock'] > 0)
        ]
        
        phase_out_count = len(phase_out_df)
        phase_out_stock = phase_out_df['Current Stock'].sum()
        phase_out_value = phase_out_df['Inventory_Value'].sum()
        
        # Beräkna konsumtion för phase out artiklar (senaste 4 veckor)
        if self.df_weekly is not None and not phase_out_df.empty:
            recent_weeks = sorted(self.available_weeks, reverse=True)[:4]
            phase_out_skus = phase_out_df['SK Number'].tolist()
            recent_consumption = self.df_weekly[
                (self.df_weekly['SK Number'].isin(phase_out_skus)) & 
                (self.df_weekly['Week'].isin(recent_weeks))
            ]['Quantity'].sum()
        else:
            recent_consumption = 0
        
        self.skapa_kpi_kort_small(kpi_frame, "Phase Out Items", f"{phase_out_count}", "#e74c3c")
        self.skapa_kpi_kort_small(kpi_frame, "Phase Out Stock", f"{phase_out_stock:,.0f}", "#e67e22")
        self.skapa_kpi_kort_small(kpi_frame, "Phase Out Value", f"{phase_out_value:,.0f} kr", "#c0392b")
        self.skapa_kpi_kort_small(kpi_frame, "Last 4 weeks sold", f"{recent_consumption:,.0f}", "#27ae60")
        
        # 3. FILTER PANEL
        filter_frame = tk.Frame(self.main_area, bg=self.c_main_bg, padx=30, pady=10)
        filter_frame.pack(fill="x")
        
        tk.Label(filter_frame, text="Filters:", bg=self.c_main_bg, fg="black", font=("Arial", 11, "bold")).pack(side="left", padx=5)
        
        # Status filter
        status_filter_var = tk.StringVar(value="Show All")
        status_combo = ttk.Combobox(filter_frame, textvariable=status_filter_var, width=15,
                                     values=["Show All", "Phase Out Only", "Active Only", "Discontinued Only"])
        status_combo.pack(side="left", padx=10)
        
        # Stock filter
        stock_filter_var = tk.StringVar(value="With Stock")
        stock_combo = ttk.Combobox(filter_frame, textvariable=stock_filter_var, width=15,
                                    values=["With Stock", "All Items", "No Stock"])
        stock_combo.pack(side="left", padx=10)
        
        # Trend filter
        trend_filter_var = tk.StringVar(value="All Trends")
        trend_combo = ttk.Combobox(filter_frame, textvariable=trend_filter_var, width=15,
                                    values=["All Trends", "Decreasing", "Increasing", "Stable"])
        trend_combo.pack(side="left", padx=10)
        
        # Sökruta
        search_frame = tk.Frame(filter_frame, bg=self.c_main_bg)
        search_frame.pack(side="right")
        tk.Label(search_frame, text="Search SKU:", bg=self.c_main_bg, fg="black").pack(side="left", padx=5)
        search_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=search_var, width=20).pack(side="left", padx=5)
        
        # 4. HUVUDPANEL (2 kolumner)
        main_content = tk.Frame(self.main_area, bg=self.c_main_bg)
        main_content.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Vänster: Tabell
        left_frame = tk.Frame(main_content, bg=self.c_main_bg)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        # Höger: Charts och detaljer
        right_frame = tk.Frame(main_content, bg=self.c_main_bg)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))
        
        # 4A. TABELL FÖR CONSUMPTION
        tk.Label(left_frame, text="Weekly Consumption Details", font=("Arial", 16, "bold"), 
                 bg=self.c_main_bg, fg="black").pack(anchor="w", pady=(0, 10))
        
        table_frame = tk.Frame(left_frame, bg="white", bd=1, relief="solid")
        table_frame.pack(fill="both", expand=True)
        
        # Definiera kolumner baserat på valda veckor
        week_columns = []
        if self.df_weekly is not None and not self.selected_weeks:
            # Visa senaste 4 veckorna som standard
            self.selected_weeks = sorted(self.available_weeks, reverse=True)[:4]
        
        if self.selected_weeks:
            week_columns = [f"Week {w}" for w in self.selected_weeks]
        
        columns = ["SK Number", "Description", "Status", "Stock", "4wk Total", "Trend"] + week_columns
        
        # Skapa trädvy med scrollbar
        scrollbar_y = ttk.Scrollbar(table_frame, orient="vertical")
        scrollbar_x = ttk.Scrollbar(table_frame, orient="horizontal")
        
        self.cons_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                       yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        scrollbar_y.config(command=self.cons_tree.yview)
        scrollbar_x.config(command=self.cons_tree.xview)
        
        # Konfigurera kolumnbredder
        col_widths = {
            "SK Number": 100, "Description": 250, "Status": 100, 
            "Stock": 80, "4wk Total": 90, "Trend": 80
        }
        
        for col in columns:
            width = col_widths.get(col, 70)
            self.cons_tree.column(col, width=width, anchor="center" if col != "Description" else "w")
            self.cons_tree.heading(col, text=col)
        
        self.cons_tree.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        
        # Binda dubbelklick för att visa detaljer
        self.cons_tree.bind("<Double-1>", self.oppna_consumption_detalj)
        
        # 4B. DIAGRAM OCH ANALYS (Höger sida)
        # Diagramruta 1: Top 10 konsumerande artiklar
        chart1_frame = tk.Frame(right_frame, bg="white", bd=1, relief="solid")
        chart1_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        tk.Label(chart1_frame, text="Top 10 Consuming Items (Last 4 Weeks)", 
                 font=("Arial", 12, "bold"), bg="white", fg="black").pack(pady=10)
        
        self.skapa_top10_chart(chart1_frame)
        
        # Diagramruta 2: Trendanalys
        chart2_frame = tk.Frame(right_frame, bg="white", bd=1, relief="solid")
        chart2_frame.pack(fill="both", expand=True)
        
        tk.Label(chart2_frame, text="Consumption Trend Analysis", 
                 font=("Arial", 12, "bold"), bg="white", fg="black").pack(pady=10)
        
        self.skapa_trend_analys(chart2_frame)
        
        # Ladda data i tabellen
        self.uppdatera_consumption_tabell(status_filter_var.get(), stock_filter_var.get(), 
                                          trend_filter_var.get(), search_var.get())
        
        # Bind filterändringar
        for var in [status_filter_var, stock_filter_var, trend_filter_var]:
            var.trace("w", lambda *args: self.uppdatera_consumption_tabell(
                status_filter_var.get(), stock_filter_var.get(), trend_filter_var.get(), search_var.get()))
        
        search_var.trace("w", lambda *args: self.uppdatera_consumption_tabell(
            status_filter_var.get(), stock_filter_var.get(), trend_filter_var.get(), search_var.get()))

    def skapa_kpi_kort_small(self, parent, titel, varde, farg):
        card = tk.Frame(parent, bg="white", bd=1, relief="raised", padx=10, pady=10)
        card.pack(side="left", fill="both", expand=True, padx=5)
        tk.Label(card, text=titel, bg="white", fg="#7f8c8d", font=("Arial", 9)).pack()
        tk.Label(card, text=varde, bg="white", fg=farg, font=("Arial", 14, "bold")).pack(pady=(5, 0))

    def skapa_veckoanalys(self):
        """Skapar veckovis analys av outbound-data"""
        if self.df_outbound is None:
            return
            
        try:
            # Robust detection: SKU, date and qty columns (case-insensitive)
            sku_col = next((c for c in self.df_outbound.columns if any(k in c.lower() for k in ['sk ', 'sku', 'item', 'article'])), None)
            date_col = next((c for c in self.df_outbound.columns if any(k in c.lower() for k in ['date', 'confirmed', 'delivery', 'orderdate'])), None)
            qty_col = next((c for c in self.df_outbound.columns if any(k in c.lower() for k in ['qty', 'quantity', 'unit', 'units', 'amount'])), None)

            if not sku_col or not date_col or not qty_col:
                # Not enough data to create weekly analysis
                return

            # Kopiera och rensa data
            df = self.df_outbound.copy()
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.dropna(subset=[date_col])

            # Lägg till veckonummer och år
            df['Week'] = df[date_col].dt.isocalendar().week
            df['Year'] = df[date_col].dt.isocalendar().year
            df['YearWeek'] = df['Year'] * 100 + df['Week']

            # Gruppera per SKU och vecka
            weekly_data = df.groupby([sku_col, 'YearWeek', 'Week', 'Year'])[qty_col].sum().reset_index()
            weekly_data.rename(columns={qty_col: 'Quantity', sku_col: 'SK Number'}, inplace=True)
            
            self.df_weekly = weekly_data
            
            # Skapa lista med tillgängliga veckor
            if not weekly_data.empty:
                self.available_weeks = sorted(weekly_data['YearWeek'].unique(), reverse=True)
            else:
                self.available_weeks = []
                
            # Standardvälj senaste 4 veckor
            if self.available_weeks:
                self.selected_weeks = sorted(self.available_weeks, reverse=True)[:4]
                
        except Exception as e:
            print(f"Error creating weekly analysis: {e}")
            self.df_weekly = None
            self.available_weeks = []

    def uppdatera_veckovalg(self, val):
        """Uppdaterar valda veckor baserat på användarens val"""
        if not self.available_weeks:
            return
            
        if val == "Last 4 weeks":
            self.selected_weeks = sorted(self.available_weeks, reverse=True)[:4]
        elif val == "Last 8 weeks":
            self.selected_weeks = sorted(self.available_weeks, reverse=True)[:8]
        elif val == "Last 12 weeks":
            self.selected_weeks = sorted(self.available_weeks, reverse=True)[:12]
        elif val == "All available weeks":
            self.selected_weeks = self.available_weeks[:12]  # Max 12 veckor för att inte bli för bredd

    def uppdatera_consumption_vy(self, period):
        """Uppdaterar hela consumption-vyn"""
        self.uppdatera_veckovalg(period)
        self.visa_consumption()

    def berakna_trend(self, sku):
        """Beräknar trend för en SKU baserat på senaste 4 veckor"""
        if self.df_weekly is None:
            return "➡️", 0, "stable"
            
        try:
            # Hämta data för denna SKU
            sku_data = self.df_weekly[self.df_weekly['SK Number'] == sku]
            if sku_data.empty:
                return "➡️", 0, "stable"
                
            # Sortera veckor
            sorted_weeks = sorted(sku_data['YearWeek'].unique(), reverse=True)
            if len(sorted_weeks) < 2:
                return "➡️", 0, "stable"
                
            # Jämför två senaste veckorna som finns
            recent_weeks = sorted_weeks[:2]
            week_data = sku_data[sku_data['YearWeek'].isin(recent_weeks)]
            
            if len(week_data) < 2:
                return "➡️", 0, "stable"
                
            # Skapa dict med veckodata
            week_dict = {row['YearWeek']: row['Quantity'] for _, row in week_data.iterrows()}
            
            # Kontrollera att vi har båda veckorna
            if len(week_dict) < 2:
                return "➡️", 0, "stable"
                
            # Beräkna förändring
            latest_week = sorted(week_dict.keys(), reverse=True)[0]
            previous_week = sorted(week_dict.keys(), reverse=True)[1]
            
            latest_qty = week_dict[latest_week]
            previous_qty = week_dict[previous_week]
            
            if previous_qty == 0:
                if latest_qty > 0:
                    return "📈", 100, "up"
                else:
                    return "➡️", 0, "stable"
            
            change_pct = ((latest_qty - previous_qty) / previous_qty) * 100
            
            if change_pct > 10:
                return "📈", int(change_pct), "up"
            elif change_pct < -10:
                return "📉", int(abs(change_pct)), "down"
            else:
                return "➡️", int(abs(change_pct)), "stable"
        except Exception:
            return "➡️", 0, "stable"

    def berakna_4wk_total(self, sku):
        """Beräknar total konsumtion senaste 4 veckor"""
        if self.df_weekly is None:
            return 0
            
        try:
            sku_data = self.df_weekly[self.df_weekly['SK Number'] == sku]
            if sku_data.empty:
                return 0
                
            # Hämta senaste 4 veckor
            sorted_weeks = sorted(sku_data['YearWeek'].unique(), reverse=True)[:4]
            total = sku_data[sku_data['YearWeek'].isin(sorted_weeks)]['Quantity'].sum()
            
            return total
        except Exception:
            return 0

    def hitta_veckodata(self, sku, yearweek):
        """Hittar kvantitet för en specifik vecka"""
        if self.df_weekly is None:
            return 0
            
        try:
            data = self.df_weekly[(self.df_weekly['SK Number'] == sku) & 
                                  (self.df_weekly['YearWeek'] == yearweek)]
            
            if not data.empty:
                return int(data.iloc[0]['Quantity'])
            return 0
        except Exception:
            return 0

    def uppdatera_consumption_tabell(self, status_filter, stock_filter, trend_filter, search_text):
        """Uppdaterar consumption-tabellen med filtrerad data"""
        if self.cons_tree is None or self.df_combined is None:
            return
            
        # Rensa träd
        self.cons_tree.delete(*self.cons_tree.get_children())
        
        # Filtrera dataframe
        filtered_df = self.df_combined.copy()
        
        # Statusfilter
        if status_filter == "Phase Out Only":
            filtered_df = filtered_df[filtered_df['ITEM STATUS'].str.lower().str.contains('phase out')]
        elif status_filter == "Discontinued Only":
            filtered_df = filtered_df[filtered_df['ITEM STATUS'].str.lower().str.contains('discontinued')]
        elif status_filter == "Active Only":
            filtered_df = filtered_df[~filtered_df['ITEM STATUS'].str.lower().str.contains('phase out|discontinued')]
        
        # Lagerfilter
        if stock_filter == "With Stock":
            filtered_df = filtered_df[filtered_df['Current Stock'] > 0]
        elif stock_filter == "No Stock":
            filtered_df = filtered_df[filtered_df['Current Stock'] == 0]
        
        # Sökfilter
        if search_text:
            search_text = search_text.lower()
            filtered_df = filtered_df[
                filtered_df['SK Number'].astype(str).str.lower().str.contains(search_text) |
                filtered_df['ITEM DESCRIPTION'].astype(str).str.lower().str.contains(search_text)
            ]
        
        # Sortera efter total utbound (eller 4-veckors total om vi har veckodata)
        if self.df_weekly is not None and not filtered_df.empty:
            # Beräkna 4-veckors total för varje SKU
            four_week_totals = []
            for _, row in filtered_df.iterrows():
                total = self.berakna_4wk_total(row['SK Number'])
                four_week_totals.append(total)
            
            filtered_df = filtered_df.copy()
            filtered_df['4wk_total'] = four_week_totals
            filtered_df = filtered_df.sort_values('4wk_total', ascending=False)
        else:
            filtered_df = filtered_df.sort_values('Total_Outbound', ascending=False)
        
        # Fyll tabellen
        for idx, row in filtered_df.iterrows():
            sku = row['SK Number']
            desc = row['ITEM DESCRIPTION'][:40] + ("..." if len(row['ITEM DESCRIPTION']) > 40 else "")
            status = row['ITEM STATUS']
            stock = int(row['Current Stock'])
            
            # Beräkna 4-veckors total
            four_week_total = self.berakna_4wk_total(sku) if self.df_weekly is not None else 0
            
            # Beräkna trend
            trend_symbol, trend_pct, trend_type = self.berakna_trend(sku)
            trend_text = f"{trend_symbol} {trend_pct}%"
            
            # Trendfilter
            if trend_filter == "Decreasing" and trend_type != "down":
                continue
            elif trend_filter == "Increasing" and trend_type != "up":
                continue
            elif trend_filter == "Stable" and trend_type != "stable":
                continue
            
            # Skapa radvärden
            row_values = [sku, desc, status, stock, four_week_total, trend_text]
            
            # Lägg till veckodata
            if self.selected_weeks:
                for week in self.selected_weeks:
                    week_data = self.hitta_veckodata(sku, week)
                    row_values.append(week_data)
            
            # Lägg till i trädet
            self.cons_tree.insert("", "end", values=row_values)
            
            # Färglägg raden baserat på status
            if "phase out" in str(status).lower() and stock > 0:
                self.cons_tree.item(self.cons_tree.get_children()[-1], tags=("warning",))
            elif trend_type == "down" and four_week_total > 0:
                self.cons_tree.item(self.cons_tree.get_children()[-1], tags=("trend_down",))
            elif trend_type == "up" and four_week_total > 0:
                self.cons_tree.item(self.cons_tree.get_children()[-1], tags=("trend_up",))
        
        # Konfigurera taggar för färgläggning
        self.cons_tree.tag_configure("warning", background="#ffebee")
        self.cons_tree.tag_configure("trend_down", background="#fdeaea")
        self.cons_tree.tag_configure("trend_up", background="#e8f7ed")

    def skapa_top10_chart(self, parent):
        """Skapar diagram över top 10 konsumerande artiklar"""
        if self.df_weekly is None or self.selected_weeks is None:
            tk.Label(parent, text="No consumption data available", bg="white", fg="gray").pack(expand=True)
            return
        
        try:
            # Beräkna total per SKU för valda veckor
            weekly_totals = self.df_weekly[self.df_weekly['YearWeek'].isin(self.selected_weeks)]
            if weekly_totals.empty:
                tk.Label(parent, text="No data for selected weeks", bg="white", fg="gray").pack(expand=True)
                return
                
            sku_totals = weekly_totals.groupby('SK Number')['Quantity'].sum().reset_index()
            top_10 = sku_totals.sort_values('Quantity', ascending=False).head(10)
            
            if top_10.empty:
                tk.Label(parent, text="No consumption data", bg="white", fg="gray").pack(expand=True)
                return
            
            # Hämta beskrivningar
            top_10_with_desc = pd.merge(top_10, self.df_combined[['SK Number', 'ITEM DESCRIPTION']], 
                                        on='SK Number', how='left')
            
            # Skapa diagram
            fig, ax = plt.subplots(figsize=(8, 4))
            
            # Förkorta beskrivningar för bättre visning
            descriptions = []
            for desc in top_10_with_desc['ITEM DESCRIPTION']:
                if len(str(desc)) > 20:
                    descriptions.append(str(desc)[:18] + "...")
                else:
                    descriptions.append(str(desc))
            
            bars = ax.barh(range(len(top_10)), top_10['Quantity'], color='#3498db')
            ax.set_yticks(range(len(top_10)))
            ax.set_yticklabels(descriptions)
            ax.invert_yaxis()  # Högst upp ska ha högst värde
            ax.set_xlabel('Quantity Sold')
            ax.set_title(f'Top 10 Items (Last {len(self.selected_weeks)} weeks)')
            
            # Lägg till värden på staplarna
            for bar in bars:
                width = bar.get_width()
                ax.text(width + 1, bar.get_y() + bar.get_height()/2, 
                       f'{int(width)}', ha='left', va='center')
            
            plt.tight_layout()
            
            # Visa i Tkinter
            canvas = FigureCanvasTkAgg(fig, parent)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
            
        except Exception as e:
            tk.Label(parent, text=f"Chart error: {str(e)}", bg="white", fg="gray").pack(expand=True)

    def skapa_trend_analys(self, parent):
        """Skapar trendanalys för phase out artiklar med lager"""
        try:
            # Hitta phase out artiklar med lager
            phase_out_df = self.df_combined[
                (self.df_combined['ITEM STATUS'].str.lower().str.contains('phase out|discontinued')) & 
                (self.df_combined['Current Stock'] > 0)
            ]
            
            if phase_out_df.empty or self.df_weekly is None or not self.selected_weeks:
                tk.Label(parent, text="No phase out items with stock found", bg="white", fg="gray").pack(expand=True)
                return
            
            # Ta top 5 phase out artiklar med högst lager
            top_phase_out = phase_out_df.nlargest(5, 'Current Stock')
            
            # Skapa diagram
            fig, ax = plt.subplots(figsize=(8, 4))
            
            # Färger för linjerna
            colors = ['#e74c3c', '#e67e22', '#f1c40f', '#2ecc71', '#3498db']
            
            # För varje artikel, hämta veckodata
            for idx, (_, row) in enumerate(top_phase_out.iterrows()):
                sku = row['SK Number']
                sku_data = self.df_weekly[self.df_weekly['SK Number'] == sku]
                
                if not sku_data.empty:
                    # Filtrera på valda veckor och sortera
                    sku_weekly = sku_data[sku_data['YearWeek'].isin(self.selected_weeks)]
                    sku_weekly = sku_weekly.sort_values('YearWeek')
                    
                    if not sku_weekly.empty:
                        # Skapa veckoetiketter
                        week_labels = [f'W{w%100}' for w in sku_weekly['YearWeek']]
                        
                        # Rita linje
                        ax.plot(week_labels, sku_weekly['Quantity'], 
                               marker='o', label=f"{sku}", color=colors[idx % len(colors)])
            
            ax.set_xlabel('Week')
            ax.set_ylabel('Quantity Sold')
            ax.set_title('Phase Out Items - Weekly Consumption')
            ax.legend(title='SKU', fontsize=9)
            ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # Visa i Tkinter
            canvas = FigureCanvasTkAgg(fig, parent)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
            
        except Exception as e:
            tk.Label(parent, text=f"Chart error: {str(e)}", bg="white", fg="gray").pack(expand=True)

    def oppna_consumption_detalj(self, event):
        """Öppnar detaljvy för vald artikel i consumption-tabellen"""
        selection = self.cons_tree.selection()
        if not selection:
            return
            
        item = self.cons_tree.item(selection[0])
        sku = item['values'][0]
        
        try:
            row = self.df_combined[self.df_combined['SK Number'].astype(str) == str(sku)].iloc[0]
        except:
            return
        
        # Skapa popup-fönster
        popup = tk.Toplevel(self.root)
        popup.title(f"Consumption Details: {sku}")
        popup.geometry("800x600")
        
        # Header
        tk.Label(popup, text=row['ITEM DESCRIPTION'], font=("Arial", 14, "bold")).pack(pady=10)
        tk.Label(popup, text=f"SKU: {sku} | GP: {row['GP Number']} | Status: {row['ITEM STATUS']}").pack()
        
        # Notera om det är phase out med lager
        if "phase out" in str(row['ITEM STATUS']).lower() and row['Current Stock'] > 0:
            tk.Label(popup, text="⚠️ WARNING: Phase out item with stock!", 
                    bg="#e74c3c", fg="white", font=("Arial", 12, "bold")).pack(pady=10)
        
        # Tab för olika vyer
        tabs = ttk.Notebook(popup)
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tab 1: Veckovis konsumtion
        tab1 = tk.Frame(tabs, bg="white")
        tabs.add(tab1, text="Weekly Consumption")
        
        if self.df_weekly is not None:
            # Hämta veckodata för denna SKU
            sku_weekly = self.df_weekly[self.df_weekly['SK Number'] == sku]
            if not sku_weekly.empty:
                # Sortera efter vecka
                sku_weekly = sku_weekly.sort_values('YearWeek', ascending=False)
                
                # Skapa tabell för veckodata
                week_tree_frame = tk.Frame(tab1, bg="white")
                week_tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
                
                week_tree = ttk.Treeview(week_tree_frame, columns=("Week", "Year", "Quantity"), show="headings")
                week_tree.column("Week", width=100, anchor="center")
                week_tree.column("Year", width=100, anchor="center")
                week_tree.column("Quantity", width=150, anchor="center")
                
                week_tree.heading("Week", text="Week")
                week_tree.heading("Year", text="Year")
                week_tree.heading("Quantity", text="Quantity")
                
                for _, week_row in sku_weekly.iterrows():
                    week_tree.insert("", "end", values=(
                        week_row['Week'], 
                        week_row['Year'], 
                        int(week_row['Quantity'])
                    ))
                
                scrollbar = ttk.Scrollbar(week_tree_frame, orient="vertical", command=week_tree.yview)
                week_tree.configure(yscrollcommand=scrollbar.set)
                week_tree.pack(side="left", fill="both", expand=True)
                scrollbar.pack(side="right", fill="y")
                
                # Beräkna statistik
                total_4wk = self.berakna_4wk_total(sku)
                avg_4wk = total_4wk / min(4, len(sku_weekly)) if len(sku_weekly) > 0 else 0
                
                stats_frame = tk.Frame(tab1, bg="white", pady=10)
                stats_frame.pack(fill="x", padx=10)
                
                tk.Label(stats_frame, text=f"Last 4 weeks total: {int(total_4wk)}", 
                        font=("Arial", 10, "bold")).pack(side="left", padx=20)
                tk.Label(stats_frame, text=f"Average/week: {int(avg_4wk)}", 
                        font=("Arial", 10, "bold")).pack(side="left", padx=20)
                
                # Beräkna veckor kvar baserat på lager
                if avg_4wk > 0:
                    weeks_left = row['Current Stock'] / avg_4wk
                    tk.Label(stats_frame, text=f"Stock covers: {weeks_left:.1f} weeks", 
                            font=("Arial", 10, "bold"), 
                            fg="#e74c3c" if weeks_left < 13 else "#27ae60").pack(side="left", padx=20)
            else:
                tk.Label(tab1, text="No weekly consumption data for this item", 
                        bg="white", fg="gray").pack(pady=50)
        else:
            tk.Label(tab1, text="No consumption data loaded", 
                    bg="white", fg="gray").pack(pady=50)
        
        # Tab 2: Artikelinfo
        tab2 = tk.Frame(tabs, bg="white")
        tabs.add(tab2, text="Item Info")
        
        info_frame = tk.Frame(tab2, bg="white", padx=20, pady=20)
        info_frame.pack()
        
        def add_info_row(label, value, color="black"):
            row_frame = tk.Frame(info_frame, bg="white")
            row_frame.pack(fill="x", pady=5)
            tk.Label(row_frame, text=label, width=20, anchor="w", bg="white").pack(side="left")
            tk.Label(row_frame, text=value, bg="white", fg=color, font=("Arial", 10, "bold")).pack(side="left")
        
        add_info_row("Current Stock:", f"{int(row['Current Stock'])}")
        add_info_row("Inventory Value:", f"{row['Inventory_Value']:,.0f} kr")
        add_info_row("Total Outbound:", f"{int(row['Total_Outbound'])}")
        add_info_row("Supplier:", row['Supplier'])
        add_info_row("Lead Time:", f"{int(row['MASTER VENDOR LEADTIME'])} days")
        add_info_row("Pallets:", f"{row['Nr. of pallets']:.1f}")
        add_info_row("Monthly Storage:", f"{row['Storage_Cost_Month']:,.0f} kr")

    # =========================================================================
    # INSTÄLLNINGAR & DATA
    # =========================================================================
    def visa_installningar(self):
        self.rensa_main_area()
        tk.Label(self.main_area, text="Settings", font=("Arial", 24, "bold"), bg=self.c_main_bg, fg="black").pack(anchor="w", padx=30, pady=30)
        f = tk.Frame(self.main_area, bg="white", padx=20, pady=20); f.pack(padx=30, fill="x")
        tk.Button(f, text="Load 4 Files & Restart", command=self.ladda_nya_filer, font=("Arial", 14)).pack(pady=50)

    def ladda_sparad_databas(self):
        if os.path.exists(DATABAS_FIL):
            try:
                data = pd.read_pickle(DATABAS_FIL)
                self.df_master, self.df_stock = data.get('master'), data.get('stock')
                self.df_outbound, self.df_inbound = data.get('outbound'), data.get('inbound')
                self.berakna_data(visa_popup=False)
            except: pass

    def ladda_nya_filer(self):
        files = filedialog.askopenfilenames(title="Select 4 Excel Files", filetypes=[("Excel", "*.xlsx")])
        if not files: return
        try:
            tm, ts, to, ti = None, None, None, None
            for p in files:
                fn = os.path.basename(p).lower()
                df = pd.read_excel(p, engine='openpyxl')
                df.columns = df.columns.str.strip()
                if "master" in fn: tm = df
                elif "stock" in fn: 
                    ts = df
                    if 'Item' in ts.columns: ts.rename(columns={'Item': 'SK Number'}, inplace=True)
                elif "outbound" in fn: to = df
                elif "inbound" in fn: ti = df 
            if tm is None or ts is None:
                messagebox.showerror("Error", "Master & Stock required")
                return
            # Normalize outbound SKU column names to 'SK Number' if needed
            if to is not None:
                sku_col = next((c for c in to.columns if any(k in c.lower() for k in ['sk ', 'sku', 'item', 'article'])), None)
                if sku_col and sku_col != 'SK Number':
                    try:
                        to.rename(columns={sku_col: 'SK Number'}, inplace=True)
                    except Exception:
                        pass

            self.df_master, self.df_stock, self.df_outbound, self.df_inbound = tm, ts, to, ti
            pd.to_pickle({'master': tm, 'stock': ts, 'outbound': to, 'inbound': ti}, DATABAS_FIL)
            self.berakna_data()
            self.visa_dashboard()
            messagebox.showinfo("Done", "Data updated!")
        except Exception as e: messagebox.showerror("Error", str(e))

    def sortera_kolumn(self, col, reverse):
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try: 
            l.sort(key=lambda t: float(t[0].replace(" kr","").replace(" ","")), reverse=reverse)
        except: 
            l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l): self.tree.move(k, '', index)
        self.tree.heading(col, command=lambda: self.sortera_kolumn(col, not reverse))

if __name__ == "__main__":
    root = tk.Tk()
    app = LagerAppV12(root)
    root.mainloop()