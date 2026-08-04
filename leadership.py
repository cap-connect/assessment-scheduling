import paramiko
import numpy
import pandas as pd
from io import StringIO, BytesIO

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)

#-- Konfigurasi SFTP ----

hostname    = 'sftp10.successfactors.com'
username    = '1162981P'
password    = 'ei35Nhqg'
port        = 22

#-- Buat koneksi SFTP
transport = paramiko.Transport((hostname, port))
transport.connect(username=username, password=password)
sftp = paramiko.SFTPClient.from_transport(transport)

#-- Lihai Path directory file
remote_folder = "/outgoing/Assessments/Leadership/"

#-- Cek isi folder
files = sftp.listdir(remote_folder)

# bangun path dari nama file yang persis sama seperti listdir
result_assessment = remote_folder.rstrip("/") + "/" + "Result_assessment"
master_competency = remote_folder.rsplit("/") + "/" + "Master_competency"
result_verb = remote_folder.rstrip("/") + "/" + "Result_verbatim"

with sftp.open(result_assessment, "rb") as f:
    result_bytes = BytesIO(f.read())
with sftp.open(result_verb, "rb") as f:
    verbatim_bytes = BytesIO(f.read())
with sftp.open(master_competency, "r") as f:
    competency_bytes = BytesIO(f.read())


df_competency = pd.read_csv(competency_bytes)
df_verbatim = pd.read_excel(verbatim_bytes)

