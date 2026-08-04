import paramiko
import numpy as np
import pandas as pd
from io import StringIO, BytesIO

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)

#-- Konfigurasi SFTP ---
hostname = os.environ["SFTP_HOST"]
port = int(os.environ.get("SFTP_PORT", 22))
username = os.environ["SFTP_USERNAME"]
password = os.environ["SFTP_PASSWORD"]

#-- Buat koneksi SFTP ---
transport = paramiko.Transport((hostname, port))
transport.connect(username=username, password=password)
sftp = paramiko.SFTPClient.from_transport(transport)

#-- Lihat path directory file

remote_folder = "/outgoing/Assessments/FNT/"  # HANYA definisikan sekali di sini

# Cek isi folder
files = sftp.listdir(remote_folder)

# Bangun path dari nama file yang PERSIS sama seperti hasil listdir
result_assessment_files = remote_folder.rstrip("/") + "/" + "Result_assessment"
competency_files = remote_folder.rstrip("/") + "/" + "master_competency"
result_verbatim = remote_folder.rstrip("/") + "/" + "result_verbatim"



with sftp.open(result_assessment_files, "rb") as f:
    file_bytes = BytesIO(f.read())

with sftp.open(competency_files, "r") as f:
    competency_bytes = BytesIO(f.read())

with sftp.open(result_verbatim, "rb") as f:
    verbatim_bytes = BytesIO(f.read())

df_competency = pd.read_csv(competency_bytes)
df_verbatim = pd.read_excel(verbatim_bytes)

df_competency = df_competency.rename(columns={
    "code_behavior": "Behaviour Code",
    "code_competency": "Competency Code",
    "level": "Level"
})

df_competency["Level"] = df_competency["Level"].replace("N", 0).astype(int)
df_raw = pd.read_excel(file_bytes, dtype={"Subject User ID": str, "Participant User ID": str})

df_raw = df_raw.rename(columns={
    "Competency Name": "Position"
})

#modify dataFrame

df_result = pd.DataFrame(df_raw)
df_result['Behaviour Code'] = df_result["Behaviour Name"].str[:2]
df_result['Position'] = df_result['Position'].str.replace(" ", "", regex=False)
df_result['Position'] = df_result["Position"].str[2]

df_result = df_result.merge(
    df_competency[["Behaviour Code", "Competency Code", "Level"]],
    on="Behaviour Code",
    how="left"
)

df_result = df_result[["Document ID", "Subject User ID", "Position", "Form Title", "Form Start Date", "Participant Category", "Participant User ID", "Competency Code", "Behaviour Code", "Level", "Behaviour Rating"]]

## Filtering

df_result = df_result.dropna()


# --- Kunci grup untuk perhitungan Score (per participant + per competency) ---
group_keys = [
    "Document ID",
    "Subject User ID",
    "Participant Category",
    "Participant User ID",
    "Position",
    "Competency Code",
    "Form Title",
    "Form Start Date",
]

# --- Pivot: dari (group + Level) -> nilai MIN Behaviour Rating per Level ---
pivot = df_result.pivot_table(
    index=group_keys,
    columns="Level",
    values="Behaviour Rating",
    aggfunc="min"
)

# Pastikan semua kolom Level 0..5 ada
for lvl in range(0, 6):
    if lvl not in pivot.columns:
        pivot[lvl] = pd.NA

pivot = pivot.fillna(0)
pivot = pivot.rename(columns={i: f"L{i}" for i in range(0, 6)})
pivot = pivot.reset_index()


# --- Fungsi scoring sesuai algoritma ---
def hitung_score(row):
    p = row["Position"]
    L0, L1, L2, L3, L4, L5 = row["L0"], row["L1"], row["L2"], row["L3"], row["L4"], row["L5"]

    if p == "A":
        if L3 >= 3 and L4 >= 3 and L5 >= 3:
            return 5
        if L3 >= 3 and L4 >= 3:
            return 4
        if L3 >= 3:
            return 3
        return 2

    if p == "B":
        if L2 >= 3 and L3 >= 3 and L4 >= 3 and L5 >= 3:
            return 5
        if L2 >= 3 and L3 >= 3 and L4 >= 3:
            return 4
        if L2 >= 3 and L3 >= 3:
            return 3
        if L2 >= 3:
            return 2
        return 1

    if p == "C":
        if L1 >= 3 and L2 >= 3 and L3 >= 3 and L4 >= 3:
            return 4
        if L1 >= 3 and L2 >= 3 and L3 > 3:
            return 3
        if L1 >= 3 and L2 >= 3:
            return 2
        if L1 >= 3:
            return 1
        return 0

    if p == "D":
        if L0 >= 3 and L1 >= 3 and L2 >= 3 and L3 >= 3:
            return 3
        if L0 >= 3 and L1 >= 3 and L2 >= 3:
            return 2
        if L0 >= 3 and L1 >= 3:
            return 1
        if L0 >= 3:
            return 0
        return -1

    if p == "E":
        if L0 > 3 and L1 > 3 and L2 > 3:
            return 2
        if L0 >= 3 and L1 >= 3:
            return 1
        if L0 >= 3:
            return 0
        return -1

    if p == "F":
        if L0 == 4 and L1 == 4:
            return 1
        if L0 >= 3:
            return 0
        return -1

    return None


pivot["Score"] = pivot.apply(hitung_score, axis=1)

# --- Susun urutan kolom sesuai kebutuhan ---
df_final = pivot[
    [
        "Document ID",
        "Subject User ID",
        "Participant Category",
        "Participant User ID",
        "Position",
        "Competency Code",
        "Form Title",
        "Form Start Date",
        "Score",
    ]
]

# print(df_final)


# ============================================
# Stage 2: Total Rater x Bobot
# ============================================

# Bobot A: digunakan jika dalam 1 Document ID tidak ada Participant Category "Subordinate"
BOBOT_A = {
    'CT':  {'Manager': 80, 'Peers': 20},
    'DIR': {'Manager': 50, 'Peers': 50},
    'IMP': {'Manager': 50, 'Peers': 50},
    'IS':  {'Manager': 80, 'Peers': 20},
    'RB':  {'Manager': 50, 'Peers': 50},
    'POC': {'Manager': 80, 'Peers': 20},
}

# Bobot B: digunakan jika dalam 1 Document ID terdapat Participant Category "Subordinate"
BOBOT_B = {
    'CT':  {'Manager': 50, 'Subordinate': 30, 'Peers': 20},
    'DIR': {'Manager': 40, 'Subordinate': 20, 'Peers': 40},
    'IMP': {'Manager': 40, 'Subordinate': 20, 'Peers': 40},
    'IS':  {'Manager': 50, 'Subordinate': 30, 'Peers': 20},
    'RB':  {'Manager': 40, 'Subordinate': 20, 'Peers': 40},
    'POC': {'Manager': 40, 'Subordinate': 40, 'Peers': 20},
}

# Tentukan Document ID mana yang punya Subordinate
doc_has_subordinate = (
    df_final[df_final["Participant Category"] == "Subordinate"]["Document ID"]
    .unique()
)

# Grup per (Document ID, Subject User ID, Competency Code, Participant Category)
# → Total Score / Jumlah Rater * Bobot / 100
stage2_group_keys = ["Document ID", "Subject User ID", "Position", "Competency Code", "Participant Category", "Form Title", "Form Start Date"]

df_stage2 = (
    df_final[df_final["Participant Category"] != "Self"]
    .groupby(stage2_group_keys, as_index=False)
    .agg(
        Total_Score=("Score", "sum"),
        Jumlah_Rater=("Score", "count"),
    )
)

# Total Rater = Total Score / Jumlah Rater
df_stage2["Total_Rater"] = df_stage2["Total_Score"] / df_stage2["Jumlah_Rater"]

# Tentukan bobot per baris
def get_bobot(row):
    doc_id = row["Document ID"]
    comp_code = row["Competency Code"]
    category = row["Participant Category"]
    bobot_table = BOBOT_B if doc_id in doc_has_subordinate else BOBOT_A
    return bobot_table.get(comp_code, {}).get(category, 0)

df_stage2["Bobot"] = df_stage2.apply(get_bobot, axis=1)
df_stage2["Total_Rater_x_Bobot"] = (df_stage2["Total_Rater"] * df_stage2["Bobot"] / 100).apply(lambda x: round(x, 2))

print("\n=== Stage 2: Total Rater x Bobot ===")
# print(df_stage2)


# ============================================
# Stage 3: Cumulative per Competency Code
# ============================================

# Target per posisi
TARGET_MAP = {
    'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1, 'F': 0,
}

cumulative_keys = ["Document ID", "Subject User ID", "Form Title", "Position", "Competency Code", "Form Start Date"]

df_stage3 = (
    df_stage2
    .groupby(cumulative_keys, as_index=False)
    .agg(Cumulative=("Total_Rater_x_Bobot", "sum"))
)


# Tambahkan Total Self dari df_final
df_self = (
    df_final[df_final["Participant Category"] == "Self"]
    .groupby(["Document ID", "Subject User ID", "Competency Code"], as_index=False)
    .agg(Total_Self=("Score", "mean"))
)
df_self["Total_Self"] = df_self["Total_Self"].apply(lambda x: int(x))
df_self = df_self.rename(columns={"Total_Self": "Total Self"})

# Tambahkan Total Manager dari df_final
df_manager = (
    df_final[df_final["Participant Category"] == "Manager"]
    .groupby(["Document ID", "Subject User ID", "Competency Code"], as_index=False)
    .agg(Total_manager=("Score", "mean"))
)
df_manager["Total_manager"] = df_manager["Total_manager"].apply(lambda x: int(x))
df_manager = df_manager.rename(columns={"Total_manager": "Total Manager"})

# Tambahkan Total Peers dari df_final
df_peers = (
    df_final[df_final["Participant Category"] == "Peers"]
    .groupby(["Document ID", "Subject User ID", "Competency Code"], as_index=False)
    .agg(Total_peers=("Score", "mean"))
)
df_peers["Total_peers"] = df_peers["Total_peers"].apply(lambda x: int(x))
df_peers = df_peers.rename(columns={"Total_peers": "Total Peers"})

# Tambahkan Total Subordinate dari df_final
df_subordinate = (
    df_final[df_final["Participant Category"] == "Subordinate"]
    .groupby(["Document ID", "Subject User ID", "Competency Code"], as_index=False)
    .agg(Total_subordinate=("Score", "mean"))
)
df_subordinate["Total_subordinate"] = df_subordinate["Total_subordinate"].apply(lambda x: int(x))
df_subordinate = df_subordinate.rename(columns={"Total_subordinate": "Total Subordinate"})


df_stage3 = df_stage3.merge(
    df_self,
    on=["Document ID", "Subject User ID", "Competency Code"],
    how="left"
).merge(
    df_manager,
    on=["Document ID", "Subject User ID", "Competency Code"],
    how="left"
).merge(
    df_peers,
    on=["Document ID", "Subject User ID", "Competency Code"],
    how="left"
).merge(
    df_subordinate,
    on=["Document ID", "Subject User ID", "Competency Code"],
    how="left"
)

df_stage3["Cumulative"] = df_stage3["Cumulative"].apply(lambda x: int(x + 0.5))
df_stage3["Target"] = df_stage3["Position"].map(TARGET_MAP)
df_stage3["Future Target"] = df_stage3["Target"] + np.where(df_stage3["Target"] == 5, 0, 1)
df_stage3["Meet Target"] = (df_stage3["Cumulative"] >= df_stage3["Target"]).astype(int)
df_stage3["Future Meet Target"] = (df_stage3["Cumulative"] >= df_stage3["Future Target"]).astype(int)

print("\n=== Stage 3: Cumulative per Competency ===")
# print(df_stage3)


# ============================================
# Stage Final: Rekap per Document ID
# ============================================

final_keys = ["Document ID"]

df_stage_final = (
    df_stage3
    .groupby(final_keys, as_index=False)
    .agg(
        **{
            "Form Title": ("Form Title", "first"),
            "Subject User ID": ("Subject User ID", "first"),
            "Form Start Date": ("Form Start Date", "first"),
            "Total Self Score": ("Total Self", "sum"),
            "Total Cumulative Score": ("Cumulative", "sum"),
            "Current Target Score": ("Target", "sum"),
            "Future Target Score": ("Future Target", "sum"),
            "_Total Meet Target": ("Meet Target", "sum"),
            "_Total Future Meet Target": ("Future Meet Target", "sum"),
            "_Jumlah Competency": ("Competency Code", "count"),
        }
    )
)

# Current Percentage = (Total Meet Target / Jumlah Competency) * 100
df_stage_final["Current Percentage"] = (
    df_stage_final["_Total Meet Target"] / df_stage_final["_Jumlah Competency"] * 100
).round(0).astype(int)

# Future Percentage = (Total Future Meet Target / Jumlah Competency) * 100
df_stage_final["Future Percentage"] = (
    df_stage_final["_Total Future Meet Target"] / df_stage_final["_Jumlah Competency"] * 100
).round(0).astype(int)

df_stage_final = df_stage_final[
    [
        "Document ID",
        "Form Title",
        "Subject User ID",
        "Form Start Date",
        "Total Self Score",
        "Total Cumulative Score",
        "Current Target Score",
        "Future Target Score",
        "Current Percentage",
        "Future Percentage",
    ]
]

# ============================================
# Stage Final: Self Strength, Self Area of Improvement, Strength, Area of Improvement
# ============================================

df_verbatim["Document ID"] = df_verbatim["Document ID"].astype(str)
df_stage_final["Document ID"] = df_stage_final["Document ID"].astype(str)

_section_lower = df_verbatim["Section Name"].astype(str).str.strip().str.lower()
_is_self = df_verbatim["Participant Category"].astype(str).str.strip().str.upper() == "SELF"
_is_strength = _section_lower.str.contains("strength")
_is_improvement = _section_lower.str.contains("improvement") | _section_lower.str.contains("area")


def _join_comments(group):
    comments = group["Section Comment"].dropna().astype(str).str.strip()
    comments = comments[comments != ""]
    return "; ".join(comments)


self_strength = (
    df_verbatim[_is_self & _is_strength]
    .groupby("Document ID")
    .apply(_join_comments)
    .rename("Self Strength")
)
self_improvement = (
    df_verbatim[_is_self & _is_improvement]
    .groupby("Document ID")
    .apply(_join_comments)
    .rename("Self Area of Improvement")
)
# Selain Self (Manager, Subordinate, Peers) digabung jadi satu
other_strength = (
    df_verbatim[~_is_self & _is_strength]
    .groupby("Document ID")
    .apply(_join_comments)
    .rename("Strength")
)
other_improvement = (
    df_verbatim[~_is_self & _is_improvement]
    .groupby("Document ID")
    .apply(_join_comments)
    .rename("Area of Improvement")
)

df_stage_final = (
    df_stage_final
    .merge(self_strength, on="Document ID", how="left")
    .merge(self_improvement, on="Document ID", how="left")
    .merge(other_strength, on="Document ID", how="left")
    .merge(other_improvement, on="Document ID", how="left")
)

for _col in ["Self Strength", "Self Area of Improvement", "Strength", "Area of Improvement"]:
    df_stage_final[_col] = df_stage_final[_col].fillna("")

print("\n=== Stage Final: Rekap per Document ID ===")
# print(df_stage_final)


# ============================================
# Simpan hasil ke Excel
# # ============================================
with pd.ExcelWriter('calculation_result.xlsx') as writer:
    df_raw.to_excel(writer, sheet_name="Raw Data")
    df_result.to_excel(writer, sheet_name="Result Data", index=False)
    df_final.to_excel(writer, sheet_name="Stage 1 - Score", index=False)
    df_stage2.to_excel(writer, sheet_name="Stage 2 - Bobot", index=False)
    df_stage3.to_excel(writer, sheet_name="Stage 3 - Cumulative", index=False)
    df_stage_final.to_excel(writer, sheet_name="Stage Final - Rekap", index=False)

# df_stage2.to_excel("Calculation_stage2.xlsx", sheet_name="Calculation Stage 2", index=False)
# df_stage3.to_excel("Calculation_stage3.xlsx", sheet_name="Calculation Stage 3", index=False)
# df_stage_final.to_excel("Calculation_stege_final.xlsx", sheet_name="Calculation Stage Final", index=False)


#export to SFTP
buffer = BytesIO()
df_stage3.to_csv(buffer, index=False)
buffer.seek(0) #kembalikan posisi cursor ke wal

remote_destination = "/incoming/Assessments/FNT/testing_stage3.csv"
sftp.putfo(buffer,remote_destination)

# print(df_verbatim)
# print(df_raw)
# print(df_final)
# print(df_stage2)
# print(df_stage3)
# print(df_stage_final)
print("\nSobandi Kereeeeeeeeen")
