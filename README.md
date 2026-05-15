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

Para habilitar tradução local automática, instale e execute o Ollama no host.
O app usa o endpoint local padrão: `http://127.0.0.1:11434`.

## Onde os arquivos de trabalho ficam

- Execução em Python (desenvolvimento): `workspace/` na pasta do projeto
- Execução em `.exe` (empacotado): `%LOCALAPPDATA%\InterfaceTradutores\workspace`
- Execução empacotada no Linux: `${XDG_DATA_HOME:-~/.local/share}/InterfaceTradutores/workspace`

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

## Build Linux (onedir)

1. Abra o terminal na raiz do projeto
2. Rode:

```bash
./scripts/build_linux.sh --clean
```

Saída esperada:

```text
dist/InterfaceTradutores/InterfaceTradutores
```

Para executar o app distribuído no Linux, rode o binário `InterfaceTradutores` dentro da pasta `dist/InterfaceTradutores`.

## Fluxo no app

1. Escolher o modo (`Ren'Py`, `RPGM`, `Unity` ou `Buzz`)
2. No modo jogos: selecionar pasta do projeto (com suporte a arrastar e soltar)
3. No modo Buzz: usar a etapa 2 para gerar legendas de vídeo/áudio
4. (Ren'Py) opcional: detectar versão, executar UnRen e abrir launcher compatível
5. Executar exportação
6. Traduzir externamente e selecionar o TXT final
7. Executar importação (com pergunta de backup)

Na etapa 3 dos modos Ren'Py/RPGM/Unity, também existe a opção **Exportar + traduzir + importar automaticamente**.
Ela traduz o TXT exportado localmente via Ollama, salva uma cópia traduzida no workspace e então roda a importação normal.
Se a tradução local falhar (serviço offline, timeout, cancelamento), o app mantém o TXT exportado pronto para o fluxo manual.

Também na etapa 3 há opções para dividir/juntar TXT grande:
- **Dividir TXT gerado**: cria `parte_00.txt`, `parte_01.txt`, ... em `Downloads`.
- Na divisão, o app também grava `parte_manifest.json` para validar segurança da junção.
- **Juntar partes traduzidas**: lê `parte_*.txt` (incluindo variantes como `parte_00.en.pt.txt`), valida manifesto/ordem/partes faltantes e sobrescreve o TXT da engine no workspace (`all_translations.txt`, `rpgm_translations.txt` ou `unity_translations.txt`).
- Por padrão, após juntar com sucesso, as partes usadas são removidas automaticamente. Você pode marcar **Manter partes após juntar** para preservar os arquivos.

## Buzz Automático (legendas)

O app pode automatizar legendagem com Buzz sem precisar operar a interface manualmente.
Para isso, selecione o modo **Buzz (Legendas de Vídeo)** na etapa 1.

- Detecção: usa `flatpak` e o app `io.github.chidiwilliams.Buzz`.
- Ação: executa `flatpak run --command=buzz io.github.chidiwilliams.Buzz add ...`.
- Padrão configurado:
  - tipo: `fasterwhisper`
  - modelo: `large-v3-turbo`
  - tarefa: `transcribe`
  - saída: `SRT`
  - pasta de saída: mesma pasta do vídeo

No painel “Preparação Buzz (legendas)” você pode:

- Selecionar vídeo/áudio;
- Ajustar tipo de modelo, modelo, tarefa, idioma e extração de fala;
- Escolher formatos de saída (`SRT`, `VTT`, `TXT`);
- Definir pasta fixa de saída (ou manter mesma pasta do vídeo);
- Clicar em **Gerar legenda (Buzz)** e confirmar a execução.
- Clicar em **Gerar e traduzir legenda** para traduzir localmente a legenda gerada via Ollama e salvar uma cópia ao lado do arquivo original.

As preferências ficam salvas no mesmo arquivo de configurações do app.

### Observações e troubleshooting

- Na primeira execução de um modelo, o Buzz pode demorar para baixar/carregar os arquivos.
- A tarefa `translate` no fluxo Whisper geralmente produz saída em inglês.
- Se o app mostrar que o Buzz não está disponível:
  - verifique `flatpak --version`;
  - instale o Buzz: `flatpak install flathub io.github.chidiwilliams.Buzz`.

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
- `Executar UnRen`: no Windows usa `UnRen-forall.bat`; no Linux usa script `.sh`/executável e, para `.bat`, tenta executar via Wine (se instalado), com cópia temporária para a raiz do jogo.
- `Reverificar launchers`: procura versões em uma pasta configurada no padrão `renpy-<versão>-sdk`, com `renpy.exe` (Windows) ou `renpy.sh` (Linux) na raiz.
- `Abrir launcher`: abre o launcher compatível com a versão detectada (mesmo `major.minor`, patch mais próximo).
- `Selecionar launcher manual`: fallback quando não há compatível automático.

Após importar no Ren'Py, o app tenta copiar `force_language.rpy` para `...\game\force_language.rpy`.

Observação de segurança:

- Se você selecionar a raiz do jogo (com `game/` e `renpy/`), o export/import processa apenas `game/tl/portuguese` e não altera `game/*.rpy` nem `renpy/common`.

As configurações persistentes ficam em:

- `%LOCALAPPDATA%\InterfaceTradutores\settings.json`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/InterfaceTradutores/settings.json`

## Scripts legados (compatibilidade)

Os scripts continuam executáveis diretamente, agora usando o núcleo novo:

- `exportador_unificado.py` (Ren'Py export)
- `importador_unificado.py` (Ren'Py import)
- `extrator_rpgm.py` (RPGM export)
- `importador_rpgm.py` (RPGM import)

Esses scripts mantêm o comportamento de abrir diálogo de pasta e usar a pasta atual como workspace.
