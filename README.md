# WASD Auto Toggle

Aplicativo para Windows que alterna uma sequência configurável de teclas, por padrão `W → A → S → D`, usando `F6` como atalho global de ativação e desativação.

> **Importante:** este projeto envia eventos de teclado por `SendInput` e registra somente o atalho `F6` com `RegisterHotKey`. Ele não captura, armazena ou transmite as demais teclas digitadas. Alguns jogos e programas usam entrada de baixo nível ou mecanismos antiautomação e podem ignorar eventos simulados; não há compatibilidade universal.

## Recursos

- Ativação e desativação pelo botão da janela ou por `F6`, inclusive com a janela minimizada.
- Estado único: pressionar o botão e pressionar `F6` controlam o mesmo motor, sem criar ciclos duplicados.
- Sequência padrão `W,A,S,D`, com suporte a letras, dígitos, `F1`–`F24` e teclas especiais como `SPACE`, `ENTER`, `TAB`, `ESC`, `SHIFT`, `CTRL`, `ALT`, `LEFT`, `UP`, `RIGHT` e `DOWN`.
- Intervalo entre eventos e duração de cada pressionamento configuráveis em milissegundos.
- Configurações salvas em JSON no perfil do usuário, sem exigir administrador.
- Parada cancelável e liberação das teclas simuladas ao parar, fechar ou ocorrer uma falha.
- Interface feita com CustomTkinter e executável compilado sem console.

## Requisitos

Para executar ou compilar no Windows:

1. Windows 10 ou mais recente, 32 ou 64 bits.
2. Python 3.11 ou mais recente, instalado a partir de [python.org](https://www.python.org/downloads/windows/) com a opção **Add Python to PATH** marcada.
3. O usuário que executa o aplicativo deve ter permissão para interagir com o programa de destino. Privilégios de administrador não são solicitados pelo aplicativo.

A execução normal do aplicativo não precisa de internet. A internet é necessária apenas para instalar as dependências pela primeira vez, caso elas ainda não estejam disponíveis.

## Instalação e execução em modo de desenvolvimento

Abra o **Prompt de Comando** na pasta do projeto e execute:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Ao abrir, o aplicativo permanece **INATIVO**. Pressione `F6` para iniciar e `F6` novamente para parar. O botão da interface tem o mesmo efeito.

### Configurações

- **Intervalo entre teclas:** tempo, em milissegundos, aguardado depois que uma tecla é liberada e antes da próxima.
- **Duração de cada tecla:** tempo em que cada tecla permanece pressionada. Deve ser menor ou igual ao intervalo.
- **Sequência:** itens separados por vírgula, ponto e vírgula ou espaço; por exemplo, `W,A,S,D`.

Os limites são intervalo de `20` a `60000` ms, duração de `1` a `5000` ms e no máximo 32 teclas. As configurações são salvas automaticamente ao iniciar e pelo botão **Salvar configurações**. Alterações devem ser feitas com a automação parada.

O arquivo de configurações fica em:

- Windows: `%APPDATA%\WASD Auto Toggle\settings.json`
- Outros sistemas, para testes lógicos: `$XDG_CONFIG_HOME/wasd-auto-toggle/settings.json` ou `~/.config/wasd-auto-toggle/settings.json`

## Compilar o `.exe`

O caminho recomendado é executar o script incluído no Windows:

```bat
build.bat
```

O script cria ou reutiliza `.venv`, instala as dependências, executa os testes lógicos e somente então chama o PyInstaller. Após sucesso, o arquivo estará em:

```text
dist\WASD_Auto_Toggle.exe
```

Também é possível executar manualmente:

```bat
.venv\Scripts\activate
python -m pytest -q
python -m PyInstaller --clean --noconfirm WASD_Auto_Toggle.spec
```

O arquivo `WASD_Auto_Toggle.spec` inclui os dados do CustomTkinter, usa `console=False` e inclui `assets\icon.ico` quando o ícone está presente.

## Testes

Os testes em `tests/` são deliberadamente separados da interação real com o Windows:

```bat
python -m pytest -q
```

Eles verificam validação e persistência, repetição da sequência, respeito ao cancelamento, prevenção de dois ciclos simultâneos e liberação lógica das teclas. O teste do `RegisterHotKey`, do `SendInput` e do `.exe` precisa ser feito em uma máquina Windows, pois essas APIs não existem no ambiente Linux usado para desenvolvimento deste pacote.

Checklist manual no Windows:

1. Inicie o aplicativo e confirme que o estado inicial é **INATIVO**.
2. Com um editor de texto ou programa de teste apropriado em foco, pressione `F6` e confirme a sequência configurada.
3. Pressione `F6` novamente e confirme a parada imediata.
4. Minimize a janela, repita o teste e depois feche pelo X.
5. Confirme que nenhuma tecla permanece pressionada e que o processo termina no Gerenciador de Tarefas.
6. Altere e salve as configurações, reabra o aplicativo e confirme o carregamento.
7. Se o executável não abrir, execute temporariamente `python app.py` para obter diagnóstico e consulte o log `wasd_auto_toggle.log` no diretório pessoal do usuário.

## Estrutura

```text
WASD_Auto_Toggle/
├── app.py
├── requirements.txt
├── build.bat
├── WASD_Auto_Toggle.spec
├── README.md
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── automation.py
│   ├── hotkey_manager.py
│   ├── interface.py
│   ├── keymap.py
│   ├── keyboard_controller.py
│   └── settings_manager.py
├── assets/
│   └── icon.ico
├── tests/
│   ├── test_sequence.py
│   └── test_settings.py
└── dist/
```

A pasta `dist/` só recebe o `.exe` depois de uma compilação real no Windows; nenhum executável fictício é incluído.

## Solução de problemas

### “F6 não foi registrado”

Outro programa pode estar usando o atalho global. Feche o conflito e reinicie o aplicativo. O aplicativo exibe a falha e ainda pode ser usado pelo botão da interface.

### O programa de destino não reage

Alguns programas, jogos, ambientes com anti-cheat ou aplicações elevadas bloqueiam ou ignoram `SendInput`. O projeto não tenta contornar mecanismos de segurança. Teste em um editor simples e verifique se o programa de destino está sendo executado em um nível de integridade diferente; ainda assim, não execute o aplicativo como administrador sem uma necessidade específica.

### O PyInstaller falha

Confirme que o ambiente virtual está ativo, que o Python é 3.11 ou mais recente e execute novamente `python -m pip install -r requirements.txt`. Apague `build/` e `dist/` apenas se uma compilação anterior estiver corrompida. Se o problema estiver relacionado a antivírus, revise a quarentena conforme a política da sua organização.

### O aplicativo encerrou durante a automação

A rotina possui `finally` para liberar as teclas que ela própria pressionou. Se um programa de destino permanecer em um estado inesperado, clique nele e pressione manualmente a tecla correspondente; depois consulte o log. Não use a ferramenta em situações em que uma entrada simulada possa causar risco ou dano.

## Licença e responsabilidade

Este projeto é um exemplo de automação local para uso autorizado. Use-o somente em programas nos quais a automação seja permitida e respeite os termos de serviço, políticas de jogos e regras da sua organização.
