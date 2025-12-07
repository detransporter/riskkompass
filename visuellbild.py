import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
import os

# Fil för att spara data lokalt
DATABAS_FIL = "lager_data_v4.pkl"

class LagerAppV4:
    def __init__(self, root):
        self.root = root
        self.root.title("Lagerhantering V4 - Dashboard & Detaljvy")
        self.root.geometry("1400x900")

        # --- FÄRGER (Hårdkodade för att undvika vita-text-problem) ---
        self.c_sidebar_bg = "#f5f5f5"     # Ljus meny (ändrad så text kan vara svart)
        self.c_sidebar_fg = "black"       # Svart text i meny
        self.c_main_bg = "#ecf0f1"        # Ljusgrå bakgrund
        self.c_card_bg = "white"          # Vita kort
        self.c_text_main = "black"        # SVART TEXT (Viktigt!)
        self.c_accent = "#3498db"         # Blå accent

        # --- DATA ---
        self.df_master = None
        self.df_stock = None
        self.df_outbound = None
        self.df_inbound = None  # NYTT: Inbound fil
        self.df_combined = None
        
        self.current_view_df = None # För filtrering
        self.status_vars = {}       # För filter-checkboxar

        # --- GUI STRUKTUR ---
        # 1. Sidebar (Vänster)
        self.sidebar = tk.Frame(root, bg=self.c_sidebar_bg, width=250)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # 2. Main Content (Höger)
        self.main_area = tk.Frame(root, bg=self.c_main_bg)
        self.main_area.pack(side="right", fill="both", expand=True)

        # --- STYLING FÖR TABELLER ---
        style = ttk.Style()
        style.theme_use('default')
        
        # Tvinga svart text i tabeller
        style.configure("Treeview", 
                        background="white", 
                        foreground="black", 
                        fieldbackground="white", 
                        rowheight=25,
                        font=("Arial", 10))
        
        style.configure("Treeview.Heading", 
                        background="#d9d9d9", 
                        foreground="black", 
                        font=("Arial", 10, "bold"))
        
        # Tvinga svart text i Menus
        style.configure("TMenu",
                background="white",
                foreground="black")

        style.map('Treeview', background=[('selected', '#3498db')])

        # --- BYGG MENY ---
        self.bygg_sidebar()

        # --- STARTA ---
        # Försök ladda data, annars visa Dashboard tom
        self.ladda_sparad_databas()
        self.visa_dashboard()

    def bygg_sidebar(self):
        """Skapar knapparna i vänstermenyn"""
        # Logga/Titel
        tk.Label(self.sidebar, text="LAGER\nSYSTEM", bg=self.c_sidebar_bg, fg=self.c_sidebar_fg, 
                 font=("Arial", 20, "bold"), pady=30).pack()

        # Knappar
        self.skapa_menyknapp("📊  Dashboard", self.visa_dashboard)
        self.skapa_menyknapp("📦  Alla Artiklar", lambda: self.visa_lista("all"))
        self.skapa_menyknapp("⚠️  Overstock", lambda: self.visa_lista("overstock"))
        self.skapa_menyknapp("📉  Deadstock", lambda: self.visa_lista("deadstock"))
        self.skapa_menyknapp("📈  Konsumtion", lambda: self.visa_lista("consumption"))
        
        # Spacer
        tk.Frame(self.sidebar, bg=self.c_sidebar_bg, height=50).pack()
        
        self.skapa_menyknapp("⚙️  Inställningar / Ladda", self.visa_installningar)

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
    # VYER (PAGES)
    # =========================================================================

    def visa_dashboard(self):
        self.rensa_main_area()
        
        # Rubrik
        tk.Label(self.main_area, text="Översikt & Hälsa", font=("Arial", 24, "bold"), 
                 bg=self.c_main_bg, fg=self.c_text_main).pack(anchor="w", padx=30, pady=30)

        if self.df_combined is None:
            tk.Label(self.main_area, text="Ingen data laddad. Gå till Inställningar för att ladda filer.",
                     bg=self.c_main_bg, fg="red", font=("Arial", 14)).pack(padx=30)
            return

        # --- BERÄKNA KPI ---
        count_total = len(self.df_combined)
        count_dead = len(self.df_combined[self.df_combined['Is_Deadstock']])
        count_over = len(self.df_combined[self.df_combined['Is_Overstock']])
        
        # Inbound count (antal rader/artiklar på väg in)
        inbound_count = 0
        if self.df_inbound is not None:
            inbound_count = len(self.df_inbound)

        # KPI Rutor
        kpi_frame = tk.Frame(self.main_area, bg=self.c_main_bg)
        kpi_frame.pack(fill="x", padx=20)

        self.skapa_kpi_kort(kpi_frame, "Totalt Antal Artiklar", f"{count_total}", "#3498db")
        self.skapa_kpi_kort(kpi_frame, "Deadstock (Varning)", f"{count_dead}", "#e74c3c")
        self.skapa_kpi_kort(kpi_frame, "Overstock (Varning)", f"{count_over}", "#f39c12")
        self.skapa_kpi_kort(kpi_frame, "Inbound Rader", f"{inbound_count}", "#27ae60")

        # Info text
        tk.Label(self.main_area, text="Välj en vy i menyn till vänster för att se detaljer.", 
                 bg=self.c_main_bg, fg="#7f8c8d", pady=20).pack()

    def skapa_kpi_kort(self, parent, titel, varde, farg):
        card = tk.Frame(parent, bg="white", bd=0, relief="raised")
        card.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        
        tk.Frame(card, bg=farg, height=5).pack(fill="x") # Färglist
        tk.Label(card, text=titel, bg="white", fg="#7f8c8d", font=("Arial", 10)).pack(pady=(15,5))
        tk.Label(card, text=varde, bg="white", fg="#2c3e50", font=("Arial", 22, "bold")).pack(pady=(0,20))

    def visa_lista(self, vy_typ):
        self.rensa_main_area()
        if self.df_combined is None:
            tk.Label(self.main_area, text="Ingen data. Ladda filer först.", bg=self.c_main_bg, fg="black").pack(pady=50)
            return

        # 1. Header & Filter Panel
        top_panel = tk.Frame(self.main_area, bg=self.c_main_bg, pady=10, padx=20)
        top_panel.pack(fill="x")

        # Rubrik
        titles = {
            "all": "Alla Artiklar",
            "overstock": "⚠️ Overstock",
            "deadstock": "📉 Deadstock",
            "consumption": "📈 Konsumtion (Toplista)"
        }
        tk.Label(top_panel, text=titles.get(vy_typ, "Lista"), font=("Arial", 18, "bold"), 
                 bg=self.c_main_bg, fg="black").pack(side="left")

        # --- SÖK & FILTER ---
        filter_frame = tk.Frame(top_panel, bg=self.c_main_bg)
        filter_frame.pack(side="right")

        tk.Label(filter_frame, text="Sök:", bg=self.c_main_bg, fg="black").pack(side="left", padx=5)
        
        sv = tk.StringVar()
        sv.trace("w", lambda name, index, mode: self.uppdatera_tabell(vy_typ, sv.get()))
        tk.Entry(filter_frame, textvariable=sv, width=25, fg="black", bg="white").pack(side="left", padx=5)

        # Status Filter Knapp
        mb = tk.Menubutton(filter_frame, text="Filtrera Status ⇩", relief="raised", bg="white", fg="black", activebackground="#3498db", activeforeground="white")
        mb.menu = tk.Menu(mb, tearoff=0, fg="black", bg="white", activebackground="#3498db", activeforeground="white")
        mb["menu"] = mb.menu
        mb.pack(side="left", padx=15)
        self.bygg_status_meny(mb, vy_typ, sv)

        # Help text
        tk.Label(self.main_area, text="ℹ️ Dubbelklicka på en rad för att se detaljer", bg=self.c_main_bg, fg="#555").pack(anchor="e", padx=20)

        # 2. Tabell Area
        table_frame = tk.Frame(self.main_area, bg="white")
        table_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        cols = ("SK Number", "GP Number", "Beskrivning", "Item Status", "Lager", "Utflöde", "Inbound", "Status")
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        
        # Kolumninställningar
        self.tree.column("SK Number", width=90, anchor="center")
        self.tree.column("GP Number", width=90, anchor="center")
        self.tree.column("Beskrivning", width=300, anchor="w")
        self.tree.column("Item Status", width=100, anchor="center")
        self.tree.column("Lager", width=80, anchor="center")
        self.tree.column("Utflöde", width=80, anchor="center")
        self.tree.column("Inbound", width=80, anchor="center") # NY KOLUMN
        self.tree.column("Status", width=100, anchor="center")

        for col in cols:
            self.tree.heading(col, text=col, command=lambda c=col: self.sortera_kolumn(c, False))

        self.tree.pack(fill="both", expand=True)

        # BIND EVENT: Dubbelklick
        self.tree.bind("<Double-1>", self.oppna_detaljvy)

        # 3. Ladda data för vyn
        if vy_typ == "all":
            self.current_view_df = self.df_combined.copy()
        elif vy_typ == "overstock":
            self.current_view_df = self.df_combined[self.df_combined['Is_Overstock']].copy()
        elif vy_typ == "deadstock":
            self.current_view_df = self.df_combined[self.df_combined['Is_Deadstock']].copy()
        elif vy_typ == "consumption":
            # Bara de som rör på sig
            temp = self.df_combined[self.df_combined['Total_Outbound'] > 0].copy()
            self.current_view_df = temp.sort_values(by='Total_Outbound', ascending=False)

        self.uppdatera_tabell(vy_typ, "")

    def bygg_status_meny(self, mb, vy_typ, sv_search):
        """Bygger checkboxar i filter-menyn"""
        menu = mb.menu
        menu.delete(0, "end")
        
        # Hämta unika statusar
        if 'ITEM STATUS' in self.df_combined.columns:
            unika = sorted(self.df_combined['ITEM STATUS'].astype(str).unique())
            
            self.status_vars = {} # Återställ
            
            for status in unika:
                var = tk.BooleanVar(value=True) # Alla valda från början
                # Uppdatera tabell vid klick
                var.trace("w", lambda n, i, m: self.uppdatera_tabell(vy_typ, sv_search.get()))
                menu.add_checkbutton(label=status, variable=var, onvalue=True, offvalue=False)
                self.status_vars[status] = var

    def uppdatera_tabell(self, vy_typ, search_text):
        # Rensa
        self.tree.delete(*self.tree.get_children())
        
        df = self.current_view_df
        if df is None or df.empty: return

        # 1. Filter: Söktext
        search_text = search_text.lower()
        mask_text = (
            df['SK Number'].astype(str).str.lower().str.contains(search_text, na=False) |
            df['GP Number'].astype(str).str.lower().str.contains(search_text, na=False) |
            df['ITEM DESCRIPTION'].astype(str).str.lower().str.contains(search_text, na=False)
        )

        # 2. Filter: Status Checkboxar
        valda_statusar = [s for s, var in self.status_vars.items() if var.get()]
        mask_status = df['ITEM STATUS'].astype(str).isin(valda_statusar)

        final_df = df[mask_text & mask_status]

        # Rita ut
        for _, row in final_df.iterrows():
            calc_stat = "OK"
            if row['Is_Deadstock']: calc_stat = "DEADSTOCK"
            elif row['Is_Overstock']: calc_stat = "OVERSTOCK"

            vals = (
                row['SK Number'],
                row['GP Number'],
                row['ITEM DESCRIPTION'],
                row['ITEM STATUS'],
                int(row['Current Stock']),
                int(row['Total_Outbound']),
                int(row['Total_Inbound']),
                calc_stat
            )
            self.tree.insert("", "end", values=vals)

    # =========================================================================
    # DETALJVY (POPUP)
    # =========================================================================
    
    def oppna_detaljvy(self, event):
        """Visar ett fönster med all info om vald artikel"""
        selected_item = self.tree.selection()
        if not selected_item: return

        # Hämta data från raden
        vals = self.tree.item(selected_item)['values']
        sk_num = str(vals[0]) # SK Number är först

        # Hämta hela raden från dataframe
        row = self.df_combined[self.df_combined['SK Number'].astype(str) == sk_num].iloc[0]

        # Skapa Popup
        popup = tk.Toplevel(self.root)
        popup.title(f"Detaljer: {sk_num}")
        popup.geometry("700x500")
        popup.configure(bg="white", fg="black")

        # HEADER
        header = tk.Frame(popup, bg="#ecf0f1", pady=20)
        header.pack(fill="x")
        
        tk.Label(header, text=f"{row['ITEM DESCRIPTION']}", font=("Arial", 16, "bold"), bg="#ecf0f1", fg="black", activeforeground="black").pack()
        tk.Label(header, text=f"SK: {sk_num}  |  GP: {row['GP Number']}  |  Status: {row['ITEM STATUS']}", 
             font=("Arial", 10), bg="#ecf0f1", fg="black").pack()

        # CONTENT GRID
        content = tk.Frame(popup, bg="white", pady=20, padx=20)
        content.pack(fill="both", expand=True)

        # Vänster: Data
        left = tk.Frame(content, bg="white")
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="LAGER & FLÖDE", font=("Arial", 12, "bold", "underline"), bg="white", fg="black").pack(anchor="w", pady=(0,10))
        self.rad(left, "Nuvarande Lager:", f"{int(row['Current Stock'])}")
        self.rad(left, "Sålt (Outbound):", f"{int(row['Total_Outbound'])}")
        self.rad(left, "På väg in (Inbound):", f"{int(row['Total_Inbound'])}", farg="#27ae60")

        # Höger: Analys
        right = tk.Frame(content, bg="white")
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="ANALYS", font=("Arial", 12, "bold", "underline"), bg="white", fg="black").pack(anchor="w", pady=(0,10))
        
        status_text = "OK"
        bg_col = "#2ecc71" # Grön
        
        if row['Is_Deadstock']:
            status_text = "DEADSTOCK"
            bg_col = "#e74c3c" # Röd
        elif row['Is_Overstock']:
            status_text = "OVERSTOCK"
            bg_col = "#f39c12" # Orange

        lbl = tk.Label(right, text=status_text, bg=bg_col, fg="white", font=("Arial", 14, "bold"), padx=15, pady=5)
        lbl.pack(anchor="w", pady=10)

        # Rekommendation
        rec = ""
        if row['Is_Deadstock'] and row['Total_Inbound'] > 0:
            rec = "⚠️ KRITISKT: Varan säljer inte men mer är på väg in!\nStoppa ordern om möjligt."
        elif row['Is_Deadstock']:
            rec = "Varan står still. Överväg utförsäljning eller skrot."
        elif row['Is_Overstock']:
            rec = "Lagret är onödigt högt i förhållande till försäljning."
        
        if rec:
            tk.Label(right, text=rec, bg="white", fg="black", justify="left", font=("Arial", 10, "italic")).pack(anchor="w")

    def rad(self, parent, label, value, farg="black"):
        f = tk.Frame(parent, bg="white")
        f.pack(fill="x", pady=2)
        tk.Label(f, text=label, width=20, anchor="w", bg="white", fg="black").pack(side="left")
        tk.Label(f, text=value, anchor="w", bg="white", fg=farg, font=("Arial", 10, "bold")).pack(side="left")

    # =========================================================================
    # INSTÄLLNINGAR & DATA
    # =========================================================================

    def visa_installningar(self):
        self.rensa_main_area()
        tk.Label(self.main_area, text="Inställningar", font=("Arial", 24, "bold"), 
                 bg=self.c_main_bg, fg="black").pack(anchor="w", padx=30, pady=30)
        
        frame = tk.Frame(self.main_area, bg="white", padx=20, pady=20)
        frame.pack(padx=30, fill="x")

        tk.Label(frame, text="Hantera Data", font=("Arial", 14, "bold"), bg="white", fg="black").pack(anchor="w")
        tk.Label(frame, text="För att uppdatera systemet, välj alla 4 filerna igen (Master, Stock, Outbound, Inbound).", 
                 bg="white", fg="#555").pack(anchor="w", pady=5)

        tk.Button(frame, text="1. Ladda Filer & Starta Om", command=self.ladda_nya_filer, 
                  bg="#3498db", fg="white", font=("Arial", 12, "bold"), pady=10).pack(anchor="w", pady=20)

        tk.Button(frame, text="Rensa all sparad data", command=self.rensa_data, 
                  bg="#e74c3c", fg="white", font=("Arial", 10)).pack(anchor="w")

    def ladda_sparad_databas(self):
        if os.path.exists(DATABAS_FIL):
            try:
                data = pd.read_pickle(DATABAS_FIL)
                self.df_master = data.get('master')
                self.df_stock = data.get('stock')
                self.df_outbound = data.get('outbound')
                self.df_inbound = data.get('inbound')
                self.berakna_data(visa_popup=False)
            except Exception as e:
                print(f"Fel vid laddning: {e}")

    def ladda_nya_filer(self):
        files = filedialog.askopenfilenames(title="Markera Master, Stock, Outbound, Inbound", 
                                            filetypes=[("Excel files", "*.xlsx")])
        if not files: return
        
        try:
            tm, ts, to, ti = None, None, None, None
            for p in files:
                fn = os.path.basename(p).lower()
                df = pd.read_excel(p, engine='openpyxl')
                # Tvätta kolumner
                df.columns = df.columns.str.strip()

                if "master" in fn: tm = df
                elif "stock" in fn: 
                    ts = df
                    if 'Item' in ts.columns: ts.rename(columns={'Item': 'SK Number'}, inplace=True)
                elif "outbound" in fn: to = df
                elif "inbound" in fn: ti = df # Fånga inbound

            # Vi kräver åtminstone Master och Stock
            if tm is None or ts is None:
                messagebox.showerror("Fel", "Masterdata och Stock måste finnas med!")
                return
            
            self.df_master, self.df_stock, self.df_outbound, self.df_inbound = tm, ts, to, ti
            
            # Spara och beräkna
            data = {'master': tm, 'stock': ts, 'outbound': to, 'inbound': ti}
            pd.to_pickle(data, DATABAS_FIL)
            
            self.berakna_data()
            self.visa_dashboard() # Gå tillbaka till start
            messagebox.showinfo("Klart", "Data uppdaterad!")

        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte läsa filer: {e}")

    def berakna_data(self, visa_popup=True):
        if self.df_stock is None: return

        try:
            # 1. Outbound Sum
            out_sum = pd.DataFrame(columns=['SK Number', 'Total_Outbound'])
            if self.df_outbound is not None:
                # Hitta kvantitetskolumn dynamiskt
                q_col = next((c for c in self.df_outbound.columns if 'Qty' in c or 'Quantity' in c), None)
                if q_col:
                    out_sum = self.df_outbound.groupby('SK Number')[q_col].sum().reset_index()
                    out_sum.rename(columns={q_col: 'Total_Outbound'}, inplace=True)

            # 2. Inbound Sum (NYTT)
            in_sum = pd.DataFrame(columns=['SK Number', 'Total_Inbound'])
            if self.df_inbound is not None:
                # Gissar att Inbound har liknande kvantitet-kolumn
                q_col_in = next((c for c in self.df_inbound.columns if 'Qty' in c or 'Quantity' in c), None)
                if q_col_in:
                    in_sum = self.df_inbound.groupby('SK Number')[q_col_in].sum().reset_index()
                    in_sum.rename(columns={q_col_in: 'Total_Inbound'}, inplace=True)

            # 3. Masterdata prep
            self.df_master['SK Number'] = self.df_master['SK Number'].astype(str).str.strip()
            if 'GP Number' not in self.df_master.columns: self.df_master['GP Number'] = ""
            if 'ITEM STATUS' not in self.df_master.columns: self.df_master['ITEM STATUS'] = "Unknown"
            if 'ITEM DESCRIPTION' not in self.df_master.columns: self.df_master['ITEM DESCRIPTION'] = ""

            # 4. Merge Allt
            self.df_stock['SK Number'] = self.df_stock['SK Number'].astype(str).str.strip()
            out_sum['SK Number'] = out_sum['SK Number'].astype(str).str.strip()
            in_sum['SK Number'] = in_sum['SK Number'].astype(str).str.strip()

            merged = pd.merge(self.df_master[['SK Number', 'GP Number', 'ITEM DESCRIPTION', 'ITEM STATUS']], 
                              self.df_stock[['SK Number', 'Current Stock']], 
                              on='SK Number', how='left')
            
            merged = pd.merge(merged, out_sum, on='SK Number', how='left')
            merged = pd.merge(merged, in_sum, on='SK Number', how='left') # Merge Inbound

            # Fyll tomma
            merged['Current Stock'] = merged['Current Stock'].fillna(0)
            merged['Total_Outbound'] = merged['Total_Outbound'].fillna(0)
            merged['Total_Inbound'] = merged['Total_Inbound'].fillna(0)
            merged['GP Number'] = merged['GP Number'].fillna("")
            merged['ITEM STATUS'] = merged['ITEM STATUS'].fillna("Unknown")

            # 5. Regler
            merged['Is_Deadstock'] = (merged['Current Stock'] > 0) & (merged['Total_Outbound'] == 0)
            merged['Is_Overstock'] = (merged['Current Stock'] > (merged['Total_Outbound'] * 3)) & (merged['Total_Outbound'] > 0)

            self.df_combined = merged
            
        except Exception as e:
            print(f"Beräkningsfel: {e}")
            if visa_popup: messagebox.showerror("Fel", str(e))

    def sortera_kolumn(self, col, reverse):
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try:
            l.sort(key=lambda t: float(t[0]), reverse=reverse)
        except ValueError:
            l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l):
            self.tree.move(k, '', index)
        self.tree.heading(col, command=lambda: self.sortera_kolumn(col, not reverse))

    def rensa_data(self):
        if messagebox.askyesno("Rensa", "Vill du radera all data och starta om?"):
            if os.path.exists(DATABAS_FIL): os.remove(DATABAS_FIL)
            self.df_combined = None
            self.df_stock = None
            self.visa_dashboard()

if __name__ == "__main__":
    root = tk.Tk()
    app = LagerAppV4(root)
    root.mainloop()