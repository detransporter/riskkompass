#!/usr/bin/env python3
"""
Genererar syntetisk (påhittad) lagerdata för övning i lageranalys.

Filer som skapas:
  artiklar.csv            artikelregister (master data + ERP-parametrar)
  leverantorer.csv        leverantörer
  utleverans.csv          orderrader ut (kundorder) med ordererat/levererat antal
  inleverans.csv          inköpsorderrader med förväntat/faktiskt mottagningsdatum
  lagersaldo_manadsslut.csv   lagersaldo per artikel och månadsslut
  facit_dolda_egenskaper.csv  "Sanningen" bakom datat (ABC/XYZ, föråldrade artiklar m.m.)

Ändra parametrarna i avsnittet KONFIGURATION för att få annan storlek/period.
"""
import os
import numpy as np
import pandas as pd

# ------------------------------------------------------------------ KONFIGURATION
SEED = 42
N_ITEMS = 3000                    # antal artiklar
START = pd.Timestamp("2022-09-19")  # första datum i utdata
END = pd.Timestamp("2026-09-18")    # sista datum i utdata (~4 år)
TARGET_LINES = 450_000            # ungefärligt antal utleveransrader
OUT_DIR = "/home/claude/lagerdata"
WARMUP = 120                      # simuleringsdagar före START (tas bort i utdata)
# --------------------------------------------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)
rng = np.random.default_rng(SEED)

T = (END - START).days + 1
Ttot = T + WARMUP
all_dates = pd.date_range(START - pd.Timedelta(days=WARMUP), END)
assert len(all_dates) == Ttot
wd = all_dates.dayofweek.values
bd = np.cumsum(wd < 5)  # affärsdagsindex
first_wd = all_dates[0].dayofweek
wd_ext = (np.arange(Ttot + 150) + first_wd) % 7
yr = (np.arange(Ttot) - WARMUP) / 365.25
doy = all_dates.dayofyear.values
W = WARMUP

# ------------------------------------------------------------------ KATEGORIER
# namn: (andel, mediankostnad SEK, spridning, snitt-antal per orderrad, säsongsamplitud, topp-dag, enhet, prefix)
CATS = {
    "Fästelement":         (0.16, 3,    0.9, 40,  0.10, 150, "ST", "FE"),
    "Kullager":            (0.10, 350,  0.9, 3,   0.05, 100, "ST", "KL"),
    "Filter":              (0.09, 180,  0.7, 4,   0.15, 300, "ST", "FI"),
    "Hydraulik":           (0.10, 900,  1.0, 2,   0.10, 120, "ST", "HY"),
    "Elkomponenter":       (0.14, 120,  1.1, 8,   0.05, 60,  "ST", "EL"),
    "Kablage":             (0.09, 60,   0.8, 15,  0.05, 60,  "M",  "KA"),
    "Smörjmedel":          (0.07, 250,  0.6, 6,   0.30, 350, "L",  "SM"),
    "Verktyg":             (0.08, 400,  1.0, 2,   0.10, 90,  "ST", "VE"),
    "Förpackning":         (0.09, 15,   0.7, 60,  0.25, 320, "ST", "FO"),
    "Reservdel motor":     (0.08, 2500, 1.1, 1.5, 0.08, 200, "ST", "RM"),
}
cat_names = list(CATS)
cw = np.array([CATS[c][0] for c in cat_names])
cat_idx = rng.choice(len(cat_names), N_ITEMS, p=cw / cw.sum())
c_med = np.array([CATS[c][1] for c in cat_names])[cat_idx]
c_sig = np.array([CATS[c][2] for c in cat_names])[cat_idx]
c_qty = np.array([CATS[c][3] for c in cat_names])[cat_idx]
c_amp = np.array([CATS[c][4] for c in cat_names])[cat_idx]
c_peak = np.array([CATS[c][5] for c in cat_names])[cat_idx]

N = N_ITEMS
cost = np.round(np.maximum(0.5, c_med * rng.lognormal(0, c_sig)), 2)
qmean = np.maximum(1.0, c_qty * rng.lognormal(0, 0.3, N))

# ------------------------------------------------------------------ LEVERANTÖRER
sup_rows = []
spec = [("SE", 12, (3, 8), (0.15, 0.30)), ("DE", 10, (8, 18), (0.15, 0.35)),
        ("PL", 5, (10, 22), (0.2, 0.4)), ("IT", 5, (12, 25), (0.2, 0.4)),
        ("CN", 8, (35, 60), (0.2, 0.5)), ("TW", 3, (30, 50), (0.2, 0.45)),
        ("US", 2, (20, 35), (0.2, 0.4))]
for cc, n, ltr, cvr in spec:
    for k in range(n):
        sup_rows.append((cc, ltr, cvr))
S = len(sup_rows)
sup_id = [f"S{i+1:03d}" for i in range(S)]
sup_lt = np.array([rng.uniform(*r[1]) for r in sup_rows])
sup_cv = np.array([rng.uniform(*r[2]) for r in sup_rows])
pd.DataFrame({
    "supplier_id": sup_id,
    "supplier_name": [f"Leverantör {r[0]}-{i+1:02d}" for i, r in enumerate(sup_rows)],
    "country": [r[0] for r in sup_rows],
}).to_csv(f"{OUT_DIR}/leverantorer.csv", index=False)

sw = 1.0 / np.arange(1, S + 1) ** 0.7
sw = rng.permutation(sw)
sup_of = rng.choice(S, N, p=sw / sw.sum())
lt = np.maximum(2, np.rint(sup_lt[sup_of] * rng.uniform(0.85, 1.15, N))).astype(int)
lt_sd = np.maximum(0.5, lt * sup_cv[sup_of])

# ------------------------------------------------------------------ LIVSCYKEL
created = np.zeros(N, dtype=int)
is_new = rng.random(N) < 0.10
created[is_new] = W + rng.integers(30, T - 150, is_new.sum())

is_obs = (~is_new) & (rng.random(N) < 0.07)
obs_day = np.zeros(N, dtype=int)
obs_day[is_obs] = W + rng.integers(200, T - 100, is_obs.sum())

# ------------------------------------------------------------------ EFTERFRÅGAN
t_idx = np.arange(Ttot)
month = all_dates.month.values
dom = all_dates.day.values

wk = np.array([1.12, 1.05, 1.0, 0.98, 0.85, 0.0, 0.0])[wd]
wk = wk * np.where(month == 7, 0.55, 1.0)
xmas = ((month == 12) & (dom >= 22)) | ((month == 1) & (dom <= 6))
wk = wk * np.where(xmas, 0.35, 1.0)
wk = np.where(((month == 12) & np.isin(dom, [24, 25, 26])) | ((month == 1) & (dom == 1)), 0.0, wk)

amp = c_amp * rng.uniform(0.5, 1.5, N)
peak = c_peak + rng.normal(0, 20, N)
season = 1 + amp[:, None] * np.cos(2 * np.pi * (doy[None, :] - peak[:, None]) / 365.25)

g = rng.normal(0.03, 0.12, N)
trend = np.exp(g[:, None] * yr[None, :])

life = np.ones((N, Ttot))
for i in np.nonzero(is_obs)[0]:
    life[i] = 0.02 + 0.98 / (1 + np.exp((t_idx - obs_day[i]) / 12.0))
for i in np.nonzero(is_new)[0]:
    ramp = np.clip((t_idx - created[i]) / 90.0, 0, 1)
    life[i] = np.where(t_idx < created[i], 0.0, 0.3 + 0.7 * ramp)

promo = np.ones((N, Ttot))
for i in np.nonzero(rng.random(N) < 0.06)[0]:
    for _ in range(rng.integers(3, 7)):
        s0 = rng.integers(0, Ttot - 30)
        promo[i, s0:s0 + rng.integers(14, 29)] *= rng.uniform(2, 4)

wn = rng.gamma(3.0, 1 / 3.0, (N, Ttot // 7 + 2))[:, t_idx // 7]

lam = rng.lognormal(np.log(0.06), 1.4, N)
lam = np.clip(lam * (cost / 100.0) ** -0.2, 0.004, 4.0)

M = wk[None, :] * season * trend * life * promo * wn
lam *= TARGET_LINES / (lam[:, None] * M[:, W:]).sum()
Rate = lam[:, None] * M
counts = rng.poisson(Rate)

nz_i, nz_d = np.nonzero(counts)
cnt = counts[nz_i, nz_d]
it_l = np.repeat(nz_i, cnt)
dy_l = np.repeat(nz_d, cnt)
nl = len(it_l)
qty_l = 1 + rng.poisson(np.maximum(qmean[it_l] - 1, 0))
big = rng.random(nl) < 0.03
qty_l = np.where(big, qty_l * rng.integers(3, 9, nl), qty_l).astype(int)

D = np.bincount(it_l * Ttot + dy_l, weights=qty_l, minlength=N * Ttot).reshape(N, Ttot)
E = Rate * qmean[:, None] * 1.135  # förväntad efterfrågan (enheter/dag)

# ------------------------------------------------------------------ PLANERINGSPARAMETRAR
val12 = E[:, W:W + 365].sum(1) * cost
order = np.argsort(-val12)
cum = np.cumsum(val12[order]) / val12.sum()
abc_plan = np.empty(N, dtype="<U1")
abc_plan[order] = np.where(cum <= 0.80, "A", np.where(cum <= 0.95, "B", "C"))
z = np.where(abc_plan == "A", 1.65, np.where(abc_plan == "B", 1.28, 0.84))
Rbd = np.where(abc_plan == "A", 5, np.where(abc_plan == "B", 10, 20))
Rcal = Rbd * 1.4
offs = rng.integers(0, 20, N)

E0 = np.where(is_new, 0.0, E[:, W - 30:W + 30].mean(1))
E_launch = np.zeros(N)
for i in np.nonzero(is_new)[0]:
    E_launch[i] = E[i, created[i] + 30:created[i] + 120].mean()
E_ref = np.where(is_new, E_launch, E0)

mult = np.where(qmean >= 10, rng.choice([1, 1, 5, 10, 25], N), 1)
moq_days = rng.choice([0, 14, 30, 60, 120], N, p=[.35, .25, .20, .15, .05])
moq = np.maximum(1, np.ceil(E_ref * moq_days)).astype(float)
moq = np.ceil(moq / mult) * mult

pq = rng.choice([0, 1, 2, 3], N, p=[.70, .12, .08, .10])
pq[is_new & (pq == 3)] = 0
bias = np.ones(N)
bias[pq == 1] = rng.uniform(1.8, 3.5, (pq == 1).sum())
bias[pq == 2] = rng.uniform(0.35, 0.7, (pq == 2).sum())
s_fixed = np.ceil(E0 * (lt + Rcal) * rng.uniform(0.5, 2.5, N))
q_fixed = np.ceil(np.maximum(moq, E0 * rng.uniform(20, 90, N)) / mult) * mult
PQ_TXT = {0: "Normal", 1: "Överlager-benägen", 2: "Underlager-benägen", 3: "Fasta/föråldrade parametrar"}

K_ORDER, H_CARRY = 400.0, 0.22

# ------------------------------------------------------------------ SIMULERING
C1 = np.concatenate([np.zeros((N, 1)), np.cumsum(D, axis=1)], axis=1)
C2 = np.concatenate([np.zeros((N, 1)), np.cumsum(D ** 2, axis=1)], axis=1)

stock = np.where(is_new, 0.0, np.ceil(E0 * rng.uniform(20, 120, N)))
on_order = np.zeros(N)
shipped = np.zeros((N, Ttot))
stock_hist = np.zeros((N, Ttot), dtype=np.int64)
arr_recv = np.zeros((N, Ttot + 150))
arr_ord = np.zeros((N, Ttot + 150))
s_last = np.zeros(N)
ss_last = np.zeros(N)

po = {k: [] for k in ["po_day", "item", "qty", "arr", "recv"]}


def shift_weekend(a):
    return np.where(wd_ext[a] == 5, a + 2, np.where(wd_ext[a] == 6, a + 1, a))


# Startorder för nya artiklar
for i in np.nonzero(is_new)[0]:
    q0 = np.ceil(max(moq[i], 45 * E_launch[i] * rng.uniform(0.7, 1.6)) / mult[i]) * mult[i]
    a = created[i] - 1
    while wd_ext[a] >= 5:
        a -= 1
    arr_recv[i, a] += q0
    po["po_day"].append(max(0, a - lt[i])); po["item"].append(i)
    po["qty"].append(q0); po["arr"].append(a); po["recv"].append(q0)

POLICY_START = 45
for t in range(Ttot):
    stock += arr_recv[:, t]
    on_order -= arr_ord[:, t]
    d = D[:, t]
    sh = np.minimum(stock, d)
    stock -= sh
    shipped[:, t] = sh
    stock_hist[:, t] = stock

    if t < POLICY_START or wd[t] >= 5:
        continue
    rev = np.nonzero((created <= t) & (((bd[t] + offs) % Rbd) == 0))[0]
    if len(rev) == 0:
        continue

    a90 = np.maximum(t - 90, created[rev]); n90 = np.maximum(t - a90, 14)
    a365 = np.maximum(t - 365, created[rev]); n365 = np.maximum(t - a365, 28)
    mu90 = (C1[rev, t] - C1[rev, a90]) / n90
    mu365 = (C1[rev, t] - C1[rev, a365]) / n365
    mu = 0.5 * (mu90 + mu365)
    ex2 = (C2[rev, t] - C2[rev, a365]) / n365
    sd = np.sqrt(np.maximum(ex2 - mu365 ** 2, 0))

    L = lt[rev]; sL = lt_sd[rev]; H = L + Rcal[rev]
    ss = z[rev] * np.sqrt(H * sd ** 2 + mu ** 2 * sL ** 2)
    s = (mu * H + ss) * bias[rev]
    ss = ss * bias[rev]
    Q = np.maximum(np.sqrt(2 * mu * 365 * K_ORDER / (H_CARRY * cost[rev])), moq[rev])

    stale = pq[rev] == 3
    s = np.where(stale, s_fixed[rev], s)
    ss = np.where(stale, 0.25 * s_fixed[rev], ss)
    Q = np.where(stale, q_fixed[rev], Q)
    s_last[rev] = s; ss_last[rev] = ss

    IP = stock[rev] + on_order[rev]
    go = (IP <= s) & ((mu > 1e-4) | stale)
    if not go.any():
        continue
    r = rev[go]
    q = np.maximum(s[go] + Q[go] - IP[go], moq[r])
    q = np.ceil(q / mult[r]) * mult[r]
    n_o = len(r)
    lt_act = np.maximum(2, np.rint(rng.normal(lt[r], lt_sd[r])).astype(int))
    lt_act = lt_act + (rng.random(n_o) < 0.04) * rng.integers(7, 28, n_o)
    arr = shift_weekend(t + lt_act)
    recv = np.where(rng.random(n_o) < 0.05, np.floor(q * rng.uniform(0.6, 0.99, n_o)), q)
    arr_recv[r, arr] += recv
    arr_ord[r, arr] += q
    on_order[r] += q
    po["po_day"] += [t] * n_o; po["item"] += list(r)
    po["qty"] += list(q); po["arr"] += list(arr); po["recv"] += list(recv)

# ------------------------------------------------------------------ ARTIKELREGISTER
art_id = np.array([f"A{i+1:05d}" for i in range(N)])
pref = np.array([CATS[c][7] for c in cat_names])[cat_idx]
desc = [f"{cat_names[c]} {p}-{rng.integers(1000, 9999)}" for c, p in zip(cat_idx, pref)]
uom = np.array([CATS[c][6] for c in cat_names])[cat_idx]
created_date = np.where(
    is_new, all_dates[np.minimum(created, Ttot - 1)].strftime("%Y-%m-%d"),
    (START - pd.to_timedelta(rng.integers(400, 6000, N), unit="D")).strftime("%Y-%m-%d"))
status = np.where(is_obs & (rng.random(N) < 0.4), "Utgående", "Aktiv")

artiklar = pd.DataFrame({
    "article_id": art_id, "description": desc,
    "category": np.array(cat_names)[cat_idx], "uom": uom,
    "supplier_id": np.array(sup_id)[sup_of],
    "unit_cost_sek": cost, "moq": moq.astype(int), "order_multiple": mult,
    "lead_time_days": lt,
    "reorder_point": np.rint(s_last).astype(int),
    "safety_stock": np.rint(ss_last).astype(int),
    "created_date": created_date, "status": status,
})
artiklar.to_csv(f"{OUT_DIR}/artiklar.csv", index=False)

# ------------------------------------------------------------------ UTLEVERANS
cum_line = pd.Series(qty_l).groupby(it_l * Ttot + dy_l).cumsum().values
avail = shipped[it_l, dy_l]
ship_l = np.clip(avail - (cum_line - qty_l), 0, qty_l).astype(int)

keep = dy_l >= W
it_o, dy_o, q_o, s_o = it_l[keep], dy_l[keep] - W, qty_l[keep], ship_l[keep]
nl_day = np.bincount(dy_o, minlength=T)
o_no = (rng.random(len(dy_o)) * np.maximum(1, (nl_day[dy_o] / 2.5).astype(int))).astype(int)
okey = dy_o * 1000 + o_no
uk, inv = np.unique(okey, return_inverse=True)
cw_ = 1.0 / np.arange(1, 601) ** 0.8
cust = rng.choice(600, len(uk), p=cw_ / cw_.sum())[inv]
dates_w = all_dates[W:]
out = pd.DataFrame({
    "order_date": dates_w[dy_o].strftime("%Y-%m-%d"),
    "order_id": "SO" + dates_w[dy_o].strftime("%y%m%d") + "-" + pd.Series(o_no).astype(str).str.zfill(3).values,
    "article_id": art_id[it_o],
    "customer_id": [f"K{c+1:04d}" for c in cust],
    "qty_ordered": q_o, "qty_shipped": s_o,
})
out = out.sort_values(["order_date", "order_id", "article_id"], kind="stable").reset_index(drop=True)
out.insert(2, "order_line", out.groupby("order_id").cumcount() + 1)
out.to_csv(f"{OUT_DIR}/utleverans.csv", index=False)

# ------------------------------------------------------------------ INLEVERANS
pdf = pd.DataFrame({k: np.array(v) for k, v in po.items()})
pdf = pdf[pdf["arr"] >= W].copy()
pdf["po_day"] = pdf["po_day"].astype(int); pdf["arr"] = pdf["arr"].astype(int)
all_d_ext = pd.date_range(all_dates[0], periods=Ttot + 150)
it = pdf["item"].astype(int).values
price_drift = 1 + 0.045 * (pdf["po_day"].values - W) / 365.25
unit_price = np.round(cost[it] * price_drift * rng.normal(1.0, 0.02, len(pdf)), 2)
received = pdf["arr"].values < Ttot
exp_day = shift_weekend(pdf["po_day"].values + lt[it] + np.rint(0.5 * lt_sd[it]).astype(int))
inb = pd.DataFrame({
    "po_date": all_d_ext[pdf["po_day"].values].strftime("%Y-%m-%d"),
    "supplier_id": np.array(sup_id)[sup_of[it]],
    "article_id": art_id[it],
    "qty_ordered": pdf["qty"].astype(int).values,
    "unit_price_sek": unit_price,
    "expected_date": all_d_ext[exp_day].strftime("%Y-%m-%d"),
    "receipt_date": np.where(received, all_d_ext[np.minimum(pdf["arr"].values, Ttot + 149)].strftime("%Y-%m-%d"), ""),
    "qty_received": np.where(received, pdf["recv"].astype(int).values, np.nan),
    "status": np.where(received, "Received", "Open"),
})
inb = inb.sort_values(["po_date", "supplier_id", "article_id"], kind="stable").reset_index(drop=True)
inb.insert(0, "po_number", "PO" + (100000 + inb.groupby(["po_date", "supplier_id"]).ngroup()).astype(str))
inb.insert(1, "po_line", inb.groupby("po_number").cumcount() + 1)
inb["qty_received"] = inb["qty_received"].astype("Int64")
inb.to_csv(f"{OUT_DIR}/inleverans.csv", index=False)

# ------------------------------------------------------------------ LAGERSALDO MÅNADSSLUT
try:
    me = pd.date_range(START, END, freq="ME")
except ValueError:
    me = pd.date_range(START, END, freq="M")
snap_dates = sorted(set(list(me) + [END]))
rows = []
for sd_ in snap_dates:
    ti = (sd_ - all_dates[0]).days
    ex = created <= ti
    rows.append(pd.DataFrame({
        "snapshot_date": sd_.strftime("%Y-%m-%d"),
        "article_id": art_id[ex],
        "stock_qty": stock_hist[ex, ti],
        "stock_value_sek": np.round(stock_hist[ex, ti] * cost[ex], 2),
    }))
pd.concat(rows).to_csv(f"{OUT_DIR}/lagersaldo_manadsslut.csv", index=False)

# ------------------------------------------------------------------ FACIT
val_12m = D[:, -365:].sum(1) * cost
o2 = np.argsort(-val_12m)
c2 = np.cumsum(val_12m[o2]) / max(val_12m.sum(), 1)
abc = np.empty(N, dtype="<U1")
abc[o2] = np.where(c2 <= 0.80, "A", np.where(c2 <= 0.95, "B", "C"))
mon = pd.DataFrame(D[:, W:].T, index=all_dates[W:]).resample("MS").sum()
first_m = pd.Series(all_dates[np.minimum(created, Ttot - 1)]).dt.to_period("M").dt.to_timestamp().values
mon_vals = mon.values.astype(float)
for i in np.nonzero(is_new)[0]:
    mon_vals[mon.index.values < first_m[i], i] = np.nan
cv = np.nanstd(mon_vals, axis=0) / np.where(np.nanmean(mon_vals, axis=0) > 0, np.nanmean(mon_vals, axis=0), np.nan)
xyz = np.where(np.isnan(cv), "Z", np.where(cv < 0.5, "X", np.where(cv < 1.0, "Y", "Z")))
facit = pd.DataFrame({
    "article_id": art_id,
    "abc_class_12m_value": abc,
    "xyz_class_monthly_cv": xyz,
    "consumption_value_12m_sek": np.round(val_12m, 0),
    "is_new_item": is_new,
    "is_becoming_obsolete": is_obs,
    "obsolete_from_date": np.where(is_obs, all_dates[np.minimum(obs_day, Ttot - 1)].strftime("%Y-%m-%d"), ""),
    "parameter_quality": [PQ_TXT[p] for p in pq],
    "has_promotion_spikes": (promo.max(axis=1) > 1.0),
    "seasonal_amplitude": np.round(amp, 2),
})
facit.to_csv(f"{OUT_DIR}/facit_dolda_egenskaper.csv", index=False)

# ------------------------------------------------------------------ KONTROLLSIFFROR
fr = out["qty_shipped"].sum() / out["qty_ordered"].sum()
line_ok = (out["qty_shipped"] >= out["qty_ordered"]).mean()
stk = pd.concat(rows)
tot_val = stk.groupby("snapshot_date")["stock_value_sek"].sum()
cogs_y = (D[:, -365:].sum(1) * cost).sum()
print(f"Artiklar: {N}, utleveransrader: {len(out):,}, inleveransrader: {len(inb):,}, saldorader: {len(stk):,}")
print(f"Fyllnadsgrad (antal): {fr:.3f}, rader helt levererade: {line_ok:.3f}")
print(f"Lagervärde (MSEK) start/mitt/slut: {tot_val.iloc[0]/1e6:.1f} / {tot_val.iloc[len(tot_val)//2]/1e6:.1f} / {tot_val.iloc[-1]/1e6:.1f}")
print(f"Förbrukningsvärde senaste 12 mån (MSEK): {cogs_y/1e6:.1f}, omsättningshastighet ≈ {cogs_y/tot_val.iloc[-1]:.1f}")
end_stock = stock_hist[:, -1]
dem_day = D[:, -365:].sum(1) / 365
cover = np.where(dem_day > 0, end_stock / np.maximum(dem_day, 1e-9), np.where(end_stock > 0, 9999, 0))
print(f"Artiklar med >365 dagars täckning: {(cover>365).mean():.1%}, utan förbrukning 12 mån men med saldo: {((dem_day==0)&(end_stock>0)).mean():.1%}")
print("Öppna inköpsorderrader:", (inb['status'] == 'Open').sum())
print("Inleverans i tid (≤ förväntat datum):",
      (pd.to_datetime(inb.loc[inb.status=='Received','receipt_date']) <= pd.to_datetime(inb.loc[inb.status=='Received','expected_date'])).mean().round(3))
print(out.head(3).to_string()); print(inb.head(3).to_string())
