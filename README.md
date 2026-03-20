# Interface Tradutores (V1)

Aplicação desktop em Python para simplificar o fluxo de exportação/importação de textos de jogos Ren'Py, RPGM e Unity.

## Como executar

```bash
python app.py
```

## Dependências opcionais / runtime (modo Python)

Para habilitar drag-and-drop e leitura de bundles Unity:

```bash
pip install tkinterdnd2 UnityPy
```

Sem essa dependência, o app continua funcionando normalmente pelo botão de seleção.

## Onde os arquivos de trabalho ficam

- Execução em Python (desenvolvimento): `workspace/` na pasta do projeto
- Execução em `.exe` (empacotado): `%LOCALAPPDATA%\InterfaceTradutores\workspace`

## Build de EXE (Windows / onedir)

1. Abra PowerShell na raiz do projeto
2. Rode:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -Clean
```

O script instala automaticamente as dependências de build (`PyInstaller` e `tkinterdnd2`) no Python ativo.

Saída esperada:

```text
dist\InterfaceTradutores\InterfaceTradutores.exe
```

Para executar o app distribuído, rode o `InterfaceTradutores.exe` dentro da pasta `dist\InterfaceTradutores`.

## Fluxo no app

1. Escolher engine (`Ren'Py`, `RPGM` ou `Unity`)
2. Selecionar pasta do projeto (com suporte a arrastar e soltar)
3. (Ren'Py) opcional: detectar versão, executar UnRen e abrir launcher compatível
4. Executar exportação
5. Traduzir externamente e selecionar o TXT final
6. Executar importação (com pergunta de backup)

## Suporte Unity (V1 offline)

No Unity, o app trabalha em modo offline (sem API/runtime):

- A entrada esperada é a raiz do jogo.
- O app resolve automaticamente a pasta `*_Data`.
- Exporta/importa apenas arquivos textuais suportados: `.json`, `.csv`, `.tsv`, `.txt`, `.xml`, `.yml`, `.yaml`.
- Ignora arquivos binários e técnicos (ex.: `.assets`, `.bundle`, `.dll`, `.exe`, `.meta`, `.manifest`).

Artefatos no workspace da engine Unity:

- `unity_translations.txt`
- `unity_placeholders.txt`
- `unity_mapa_arquivos.json`
- `unity_import_log.txt`

Limitações desta fase:

- Não altera conteúdos binários Unity (`.assets`, bundles, IL2CPP dump etc.).
- Overlay Unity ficou fora do escopo neste V1.

## Unity V1.1 (tables de idioma)

No Unity com Addressables (`StreamingAssets/aa`), o app pode detectar bundles de table de idioma.

- Na etapa 2 (Unity), use **Detectar tables de idioma**.
- Se houver múltiplas tables, selecione a desejada e clique em **Usar seleção para export/import**.
- A seleção vale para o projeto atual (sessão/configuração).
- Se nenhuma table for selecionada, o export/import Unity usa apenas arquivos textuais comuns.

## Preparação Ren'Py (V1.2)

Na etapa 2, quando a engine selecionada é Ren'Py, existe um painel extra de preparação:

- `Detectar versão`: tenta encontrar a versão lendo `renpy/version.py`, `renpy/__init__.py` e `log.txt`.
- `Executar UnRen`: copia `UnRen-forall.bat` para a raiz do jogo, abre em modo interativo e remove o BAT temporário ao avançar etapa.
- `Reverificar launchers`: procura versões em uma pasta configurada no padrão `renpy-<versão>-sdk`, com `renpy.exe` na raiz.
- `Abrir launcher`: abre o `renpy.exe` compatível com a versão detectada (mesmo `major.minor`, patch mais próximo).
- `Selecionar launcher manual`: fallback quando não há compatível automático.

Após importar no Ren'Py, o app tenta copiar `force_language.rpy` para `...\game\force_language.rpy`.

Observação de segurança:

- Se você selecionar a raiz do jogo (com `game/` e `renpy/`), o export/import processa apenas `game/tl/portuguese` e não altera `game/*.rpy` nem `renpy/common`.

As configurações persistentes ficam em:

- `%LOCALAPPDATA%\InterfaceTradutores\settings.json`

## Scripts legados (compatibilidade)

Os scripts continuam executáveis diretamente, agora usando o núcleo novo:

- `exportador_unificado.py` (Ren'Py export)
- `importador_unificado.py` (Ren'Py import)
- `extrator_rpgm.py` (RPGM export)
- `importador_rpgm.py` (RPGM import)

Esses scripts mantêm o comportamento de abrir diálogo de pasta e usar a pasta atual como workspace.
