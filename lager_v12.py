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
        self.root.title("Inventory Management V12 - Pallet Tracking")
        self.root.geometry("1600x950")

        # --- FÄRGER ---
        self.c_sidebar_bg = "#f5f5f5"
        self.c_sidebar_fg = "black"
        self.c_main_bg = "#ecf0f1"
        self.c_text_main = "black"
        self.c_accent = "#e74c3c" 

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
                q = next((c for c in self.df_outbound.columns if 'Qty' in c or 'Quantity' in c), None)
                if q: out_sum = self.df_outbound.groupby('SK Number')[q].sum().reset_index().rename(columns={q: 'Total_Outbound'})
            
            in_sum = pd.DataFrame(columns=['SK Number', 'Total_Inbound'])
            if self.df_inbound is not None:
                q = next((c for c in self.df_inbound.columns if 'Qty' in c or 'Quantity' in c), None)
                if q: in_sum = self.df_inbound.groupby('SK Number')[q].sum().reset_index().rename(columns={q: 'Total_Inbound'})

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
                core_cols = ['SK Number', 'GP Number', 'ITEM DESCRIPTION', 'ITEM STATUS', 'Current Stock', 'Total_Outbound']
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

    def visa_installningar(self):
        self.rensa_main_area()
        tk.Button(self.main_area, text="Load 4 Files & Restart", command=self.ladda_nya_filer, font=("Arial", 14)).pack(pady=50)

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