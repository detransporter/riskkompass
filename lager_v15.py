import sys
import pandas as pd
import traceback
try:
    import tkinter as tk
    from tkinter import messagebox
    _tk_root = tk.Tk()
    _tk_root.withdraw()
except Exception:
    class _MsgStub:
        @staticmethod
        def showerror(title, msg):
            print(f"messagebox.showerror: {title}: {msg}")
    messagebox = _MsgStub()


def skapa_veckoanalys(self):
    """Skapar veckovis analys av outbound-data"""
    if self.df_outbound is None:
        print("DEBUG: Ingen outbound-data laddad")
        return
        
    try:
        print("="*50)
        print("DEBUG: Startar veckoanalys")
        print(f"Outbound dataframe shape: {self.df_outbound.shape}")
        print(f"Outbound kolumner: {list(self.df_outbound.columns)}")
        
        # Visa lite data för att se strukturen
        print("\nFörsta 5 raderna i outbound:")
        print(self.df_outbound.head())
        
        # Hitta SKU-kolumn
        sku_col = None
        sku_candidates = []
        for col in self.df_outbound.columns:
            col_str = str(col)
            col_lower = col_str.lower()
            if any(k in col_lower for k in ['sk', 'sku', 'item', 'article', 'product', 'artikelnr', 'artikel']):
                sku_candidates.append(col)
        
        if sku_candidates:
            # Föredra 'SK Number' om den finns, annars ta första
            for cand in sku_candidates:
                if 'sk' in str(cand).lower():
                    sku_col = cand
                    break
            if not sku_col:
                sku_col = sku_candidates[0]
        
        # Hitta datumkolumn - försök flera möjligheter
        date_col = None
        date_candidates = []
        
        # Först kolla exakta matchningar
        exact_date_cols = ['originaldeliverydate', 'OriginalDeliveryDate', 'DeliveryDate', 'deliverydate']
        for col in self.df_outbound.columns:
            col_str = str(col).replace(' ', '').replace('_', '').replace('-', '').lower()
            for date_pattern in exact_date_cols:
                if date_pattern in col_str:
                    date_candidates.append(col)
                    break
        
        # Om inga exakta matchningar, kolla för andra datumindikatorer
        if not date_candidates:
            for col in self.df_outbound.columns:
                col_str = str(col).lower()
                if any(term in col_str for term in ['date', 'datum', 'delivery', 'order', 'confirmed', 'lev']):
                    date_candidates.append(col)
        
        if date_candidates:
            # Prioritera de som innehåller "delivery"
            for cand in date_candidates:
                if 'delivery' in str(cand).lower():
                    date_col = cand
                    break
            if not date_col:
                date_col = date_candidates[0]
        
        # Hitta kvantitetskolumn
        qty_col = None
        qty_candidates = []
        for col in self.df_outbound.columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in ['qty', 'quantity', 'unit', 'units', 'amount', 'st', 'antal', 'mängd']):
                qty_candidates.append(col)
        
        if qty_candidates:
            # Prioritera 'quantity' eller 'qty'
            for cand in qty_candidates:
                if 'quantity' in str(cand).lower() or 'qty' in str(cand).lower():
                    qty_col = cand
                    break
            if not qty_col:
                qty_col = qty_candidates[0]
        
        print(f"\nDEBUG: Hittade kolumner -> SKU: {sku_col}, Date: {date_col}, Quantity: {qty_col}")
        
        if not sku_col or not date_col or not qty_col:
            error_msg = f"Kan inte hitta alla nödvändiga kolumner:\n"
            error_msg += f"SKU-kolumn: {sku_col or 'Ej hittad'}\n"
            error_msg += f"Datumkolumn: {date_col or 'Ej hittad'}\n"
            error_msg += f"Kvantitetskolumn: {qty_col or 'Ej hittad'}\n"
            error_msg += f"Tillgängliga kolumner: {', '.join(self.df_outbound.columns)}"
            print(f"ERROR: {error_msg}")
            messagebox.showerror("Kolumnhittningsfel", error_msg)
            return
        
        # Kopiera och rensa data
        df = self.df_outbound.copy()
        
        # Visa exempel på data från de hittade kolumnerna
        print(f"\nDEBUG: Exempel på data från hittade kolumner:")
        sample_df = df[[sku_col, date_col, qty_col]].head(10)
        print(sample_df.to_string())
        
        # Rensa SKU-kolumn
        df['SKU_CLEANED'] = df[sku_col].astype(str).str.strip()
        
        # Prova att konvertera datum på flera sätt
        print(f"\nDEBUG: Försöker konvertera datumkolumn: '{date_col}'")
        print(f"Datumvärden (första 5): {df[date_col].head().tolist()}")
        print(f"Datumtyp före konvertering: {df[date_col].dtype}")
        
        # Försök flera datumformat
        original_dates = df[date_col].copy()
        converted = False
        
        # Försök 1: Pandas to_datetime med infer
        try:
            df['DATE_CONVERTED'] = pd.to_datetime(df[date_col], errors='coerce', infer_datetime_format=True)
            valid_count = df['DATE_CONVERTED'].notna().sum()
            print(f"Konvertering med infer_datetime_format: {valid_count}/{len(df)} giltiga datum")
            if valid_count > 0:
                converted = True
        except Exception as e:
            print(f"Fel vid infer_datetime_format: {e}")
        
        # Försök 2: Specifika format
        if not converted or df['DATE_CONVERTED'].isna().all():
            date_formats = [
                '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d.%m.%Y', '%Y.%m.%d',
                '%d-%m-%Y', '%Y/%m/%d', '%d %b %Y', '%d %B %Y', '%Y%m%d',
                '%d/%m/%y', '%m/%d/%y', '%d-%m-%y', '%y-%m-%d'
            ]
            
            for fmt in date_formats:
                try:
                    temp_dates = pd.to_datetime(df[date_col], format=fmt, errors='coerce')
                    valid_count = temp_dates.notna().sum()
                    print(f"Format {fmt}: {valid_count}/{len(df)} giltiga datum")
                    if valid_count > valid_count:
                        df['DATE_CONVERTED'] = temp_dates
                        converted = True
                        break
                except:
                    continue
        
        # Försök 3: Dayfirst för europeiska datum
        if not converted or df['DATE_CONVERTED'].isna().all():
            try:
                df['DATE_CONVERTED'] = pd.to_datetime(df[date_col], errors='coerce', dayfirst=True)
                valid_count = df['DATE_CONVERTED'].notna().sum()
                print(f"Konvertering med dayfirst=True: {valid_count}/{len(df)} giltiga datum")
                if valid_count > 0:
                    converted = True
            except Exception as e:
                print(f"Fel vid dayfirst=True: {e}")
        
        # Kontrollera resultat
        if not converted or df['DATE_CONVERTED'].isna().all():
            print("ERROR: Kunde inte konvertera några datum!")
            print("Exempel på datumvärden som kunde inte konverteras:")
            for i, val in enumerate(original_dates.head(10)):
                print(f"  Rad {i}: '{val}' (typ: {type(val).__name__})")
            
            # Skapa ett testfönster för att visa datumproblemet
            self.visa_datumproblem(original_dates.head(20))
            return
        
        # Rensa bort rader med ogiltiga datum
        original_count = len(df)
        df_clean = df[df['DATE_CONVERTED'].notna()].copy()
        print(f"\nDEBUG: Rader efter borttagning av ogiltiga datum: {len(df_clean)}/{original_count}")
        
        if df_clean.empty:
            print("ERROR: Inga rader med giltiga datum kvar!")
            messagebox.showerror("Datumfel", "Inga giltiga datum kunde hittas i utbound-datan.")
            return
        
        # Lägg till veckonummer och år
        df_clean['Week'] = df_clean['DATE_CONVERTED'].dt.isocalendar().week
        df_clean['Year'] = df_clean['DATE_CONVERTED'].dt.isocalendar().year
        df_clean['YearWeek'] = df_clean['Year'] * 100 + df_clean['Week']
        
        # Rensa kvantitetskolumn - försök konvertera till numerisk
        try:
            df_clean['QTY_CLEANED'] = pd.to_numeric(df_clean[qty_col], errors='coerce').fillna(0)
        except:
            df_clean['QTY_CLEANED'] = 0
        
        # Gruppera per SKU och vecka
        weekly_data = df_clean.groupby(['SKU_CLEANED', 'YearWeek', 'Week', 'Year'])['QTY_CLEANED'].sum().reset_index()
        weekly_data.rename(columns={'SKU_CLEANED': 'SK Number', 'QTY_CLEANED': 'Quantity'}, inplace=True)
        
        # Konvertera SK Number till string och strip
        weekly_data['SK Number'] = weekly_data['SK Number'].astype(str).str.strip()
        
        self.df_weekly = weekly_data
        
        # Visa statistik
        print(f"\nDEBUG: Veckoanalys skapad med {len(weekly_data)} rader")
        print(f"Unika SKU: {weekly_data['SK Number'].nunique()}")
        print(f"Unika veckor: {weekly_data['YearWeek'].nunique()}")
        print(f"Datumspann: {df_clean['DATE_CONVERTED'].min()} till {df_clean['DATE_CONVERTED'].max()}")
        
        if not weekly_data.empty:
            print(f"\nExempel på veckodata (första 10 rader):")
            print(weekly_data.head(10))
            
            # Visa veckor med mest data
            print(f"\nVeckor med data:")
            week_summary = weekly_data.groupby('YearWeek')['Quantity'].sum().reset_index()
            print(week_summary.sort_values('YearWeek', ascending=False).head(10))
        
        # Skapa lista med tillgängliga veckor
        if not weekly_data.empty:
            self.available_weeks = sorted(weekly_data['YearWeek'].unique(), reverse=True)
            print(f"\nTillgängliga veckor ({len(self.available_weeks)} st): {self.available_weeks}")
        else:
            self.available_weeks = []
            print("VARNING: Inga veckor hittades i datan")
            
        # Standardvälj senaste 4 veckor
        if self.available_weeks:
            self.selected_weeks = sorted(self.available_weeks, reverse=True)[:4]
            print(f"Valda veckor (standard): {self.selected_weeks}")
        
        print("="*50)
                
    except Exception as e:
        print(f"ERROR: Oväntat fel i veckoanalys: {e}")
        import traceback
        traceback.print_exc()
        self.df_weekly = None
        self.available_weeks = []
        messagebox.showerror("Analysfel", f"Fel vid skapande av veckoanalys:\n{str(e)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 lager_v15.py path/to/outbound.xlsx")
        sys.exit(1)
    path = sys.argv[1]
    try:
        df = pd.read_excel(path, engine='openpyxl')
    except Exception as e:
        print(f"Failed to read '{path}': {e}")
        sys.exit(1)

    # Minimal runner object that provides the attributes/methods expected by the function
    class Runner:
        pass

    def visa_datumproblem(self, sample):
        print("\n--- DATE PROBLEM SAMPLE ---")
        print(sample)

    Runner.visa_datumproblem = visa_datumproblem
    Runner.skapa_veckoanalys = skapa_veckoanalys

    runner = Runner()
    runner.df_outbound = df
    runner.df_weekly = None
    runner.available_weeks = []
    runner.selected_weeks = []

    print("START: Calling skapa_veckoanalys() on loaded dataframe")
    try:
        runner.skapa_veckoanalys()
    except Exception as e:
        print("Unexpected error while running skapa_veckoanalys:", e)
        traceback.print_exc()
        sys.exit(1)

    if getattr(runner, 'df_weekly', None) is not None:
        print("\n=== Weekly summary ===")
        try:
            print(runner.df_weekly.head(20).to_string(index=False))
            print(f"\nUnique SKUs: {runner.df_weekly['SK Number'].nunique()}")
            print(f"Total rows: {len(runner.df_weekly)}")
        except Exception as e:
            print("Error printing df_weekly summary:", e)
    else:
        print("No df_weekly produced.")
    # Save weekly output to Excel for downstream use
    try:
        out_path = 'weekly_outbound.xlsx'
        if getattr(runner, 'df_weekly', None) is not None and not runner.df_weekly.empty:
            runner.df_weekly.to_excel(out_path, index=False, engine='openpyxl')
            print(f"Saved weekly aggregation to: {out_path}")
        else:
            print("No weekly data to save.")
    except Exception as e:
        print(f"Failed to write weekly_outbound.xlsx: {e}")