# Interface Tradutores (V1)

Aplicação desktop em Python para simplificar o fluxo de exportação/importação de textos de jogos Ren'Py e RPGM.

## Como executar

```bash
python app.py
```

## Dependência opcional (arrastar e soltar)

Para habilitar drag-and-drop da pasta na interface:

```bash
pip install tkinterdnd2
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

1. Escolher engine (`Ren'Py` ou `RPGM`)
2. Selecionar pasta do projeto
3. Executar exportação
4. Traduzir externamente e selecionar o TXT final
5. Executar importação (com pergunta de backup)

## Scripts legados (compatibilidade)

Os scripts continuam executáveis diretamente, agora usando o núcleo novo:

- `exportador_unificado.py` (Ren'Py export)
- `importador_unificado.py` (Ren'Py import)
- `extrator_rpgm.py` (RPGM export)
- `importador_rpgm.py` (RPGM import)

Esses scripts mantêm o comportamento de abrir diálogo de pasta e usar a pasta atual como workspace.
