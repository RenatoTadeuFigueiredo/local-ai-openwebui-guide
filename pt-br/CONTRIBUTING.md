# Como contribuir

> [English](../CONTRIBUTING.md) · **Português**

Correções são bem-vindas. O valor deste guia depende de ele ser exato, então uma correção que o
mantenha alinhado com a realidade vale mais do que conteúdo novo.

**Idioma:** o inglês é a fonte da verdade. O espelho em português em [`pt-br/`](../pt-br/) pode
ficar atrasado. Você **não** precisa atualizar os dois — uma atualização em português pode vir
depois.

---

## O que é mais útil

| Tipo de mudança | Observações |
|---|---|
| **Um comando que não funciona mais** | Maior valor. Inclua a versão do componente envolvido |
| **Um passo que assume demais** | Este guia é voltado a pessoas confortáveis no terminal, mas não avançadas em TI. Lacunas nessa premissa são bugs |
| **Um fato que envelheceu** | Versões, flags, endpoints, caminhos de arquivo |
| **Uma ressalva de segurança ausente** | Os documentos publicam hostnames e executam serviços; omissões importam |
| **Redação mais clara** | Só se encurtar ou remover ambiguidade |
| **Um documento novo** | Justifique — este guia se mantém pequeno de propósito |

## O que evitar

- **Adicionar opções.** Onde existem dois caminhos, o guia escolhe um. Um pull request que
  acrescenta "ou você também poderia…" precisa de um motivo.
- **Repetir a documentação upstream.** Linke em vez de duplicar material de referência.
- **Suavizar a honestidade.** Os documentos distinguem *medido* de *estimado* e *validado* de
  *pendente*. Não transforme uma estimativa em afirmação.
- **Despersonalizar o estudo de caso.** Os nomes já são placeholders (`admin`, `user-a`,
  `seudominio.com`) — mantenha-os.

---

## Estilo

- Inglês, segunda pessoa, tempo presente. Frases curtas.
- Tabelas em vez de parágrafos quando o conteúdo é enumerável.
- Blocos `bash` são digitados em um shell. Blocos `json` / `yaml` são conteúdo de arquivo.
- Qualquer coisa pulável vai em um blockquote começando com `**Optional**.`
- **Números:** o inglês usa `,` para milhar (`262,144`) e `.` para decimal (`46.5`). O espelho em
  português mantém a convenção local (`262.144` / `46,5`). IPs (`127.0.0.1`) e versões (`0.11.0`)
  ficam intactos.
- Mantenha o bloco de status no topo de cada documento verdadeiro e atualizado.

## Política de idioma

| | |
|---|---|
| **Fonte da verdade** | Inglês (`README.md`, `docs/`, `examples/`) |
| **Espelho** | Português (`pt-br/`), mesmos nomes de arquivo, mesma estrutura |
| **Paridade** | Não exigida. O português pode ficar uma revisão atrás |
| **Seletor de idioma** | Todo documento traz um seletor de idioma de uma linha no topo — mantenha-o correto ao renomear um arquivo |

---

## Antes de abrir um pull request

1. Verifique a afirmação contra o sistema real ou a documentação upstream, e diga isso na
   descrição.
2. Rode as verificações abaixo.
3. Mantenha uma mudança lógica por pull request.

```bash
# links locais resolvem, cercas balanceadas, seletores de idioma presentes
python3 - <<'PY'
from pathlib import Path
import re
FENCE = chr(96) * 3
bad = []
for f in sorted(Path('.').rglob('*.md')):
    if '.git/' in str(f):
        continue
    t = f.read_text()
    if t.count(FENCE) % 2:
        bad.append(f'{f}: cerca desbalanceada')
    if not re.search(r'^\> .*(English|Português)', t, re.M):
        bad.append(f'{f}: seletor de idioma ausente')
    for u in re.findall(r'\[[^\]]*\]\(([^)]+)\)', t) + re.findall(r'<img[^>]+src="([^"]+)"', t):
        if u.startswith(('http', '#', 'mailto:')):
            continue
        p = u.split('#')[0]
        if p and not (f.parent / p).resolve().exists():
            bad.append(f'{f}: link quebrado {u}')
print('\n'.join(bad) if bad else 'links, cercas e seletores OK')
PY

# todo bloco bash passa no parser
python3 - <<'PY'
from pathlib import Path
import re, subprocess
FENCE = chr(96) * 3
bad = 0
for f in sorted(Path('.').rglob('*.md')):
    if '.git/' in str(f):
        continue
    for m in re.finditer(FENCE + r'bash\n(.*?)' + FENCE, f.read_text(), re.S):
        code = m.group(1)
        if re.search(r'<[a-z_]+>', code):
            continue          # bloco de referência com placeholders
        if subprocess.run(['bash', '-n'], input=code, text=True, capture_output=True).returncode:
            print('erro de bash em', f)
            bad += 1
print('blocos bash OK' if not bad else f'{bad} quebrados')
PY
```

## Relatar sem pull request

Abra uma issue com o documento, o comando exato e o que aconteceu em vez do esperado. Inclua a
versão do componente envolvido. Isso basta para outra pessoa reproduzir.

## Licenciamento das contribuições

Ao contribuir, você concorda que suas mudanças são publicadas sob a mesma licença do repositório:
[CC BY 4.0](../LICENSE) para documentação, [MIT](../LICENSE-CODE) para código. Veja
[`NOTICE.md`](../NOTICE.md) para atribuição e componentes de terceiros.