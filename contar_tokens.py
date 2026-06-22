from transformers import AutoTokenizer

tok = AutoTokenizer.from_pretrained("meta-llama/Llama-3.1-8B")  # ajusta al modelo que uses
texto = open("documents/documentos_ADM_03_Protocolo_Vacaciones__EXP20261231.txt", encoding="utf-8").read()

n_char = len(texto)
n_tok = len(tok.encode(texto))
print("caracteres:", n_char)
print("tokens:", n_tok)
print("ratio char/token:", round(n_char / n_tok, 2))
