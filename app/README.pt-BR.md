# openOMSI/openHUD Map Package Creator

**ombr-mapcreator.exe**: um programa para Windows que **mostra, confere, anota, edita e gera** os pacotes de mapa (`openomsi-realmap`) deste repositório, sem abrir o jogo.
O gerador inteiro ([tools/mapgen](../tools/mapgen/)) está dentro do mesmo arquivo: não precisa de Python. English: [README.md](README.md).

© LMonteiro · [leomonteiro.eti.br](https://leomonteiro.eti.br) · [github.com/lmonteirotech](https://github.com/lmonteirotech) · [omsimods.com.br](https://omsimods.com.br)

> **Freeware, não é código aberto.** Uso livre e compartilhamento sem alterações e completo; proibido modificar, fazer engenharia reversa, vender ou renomear: veja [EULA.txt](EULA.txt),
> [LICENSE.txt](LICENSE.txt) e [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). Os pacotes que ele gera você pode compartilhar (dê crédito aos mapas e a seus autores).

## Instalar

1. Baixe `ombr-mapcreator-v1.0.0-windows.zip` nas [releases](https://github.com/lmonteirotech/openomsi-map-packages/releases) (a `app-v1.0.0`).
2. Descompacte onde quiser e rode `ombr-mapcreator.exe`. Não há instalação, e nada é gravado fora das pastas que você escolher e das suas preferências (`%APPDATA%`).
3. O Windows pode mostrar a tela de "editor desconhecido" na primeira vez (o arquivo não é assinado): *Mais informações > Executar assim mesmo*.

O programa só **lê** as suas pastas do OMSI 2. Ele grava a pasta do pacote que você pedir (uma cópia da que substitui fica em `openomsi-realmap.backups`).

## A janela

À esquerda, uma barra com sete páginas; à direita, o mapa. Arrastar move, a roda dá zoom, **o botão direito gira**, um clique inspeciona, um duplo clique enquadra o mapa todo.

### 1. Abrir um pacote ou um mapa

**Arquivo > Selecionar...** (Ctrl+O) aceita a pasta de um pacote, a pasta de um mapa (`Maps/<Mapa>`, com ou sem pacote) ou uma instalação do OMSI 2. Se o pacote está dentro da pasta de um mapa,
o mapa é lido em segundo plano; senão use **Arquivo > Associar pasta do mapa OMSI**. A janela observa os arquivos e recarrega sozinha quando o gerador ou um editor os altera.

### 2. Camadas

![Camadas](images/layers.jpg)

Tudo o que o pacote desenha (água, verde, construído, gramado, floresta, esportes, lavoura, rios, ferrovia, divisas, ruas com nomes e limites, nomes, ícones, municípios, contornos de prédios,
o terreno real), as rotas e paradas das linhas e, do mapa OMSI 2 (precisa da pasta do mapa), suas próprias vias, objetos e terreno. Chaves ligam e desligam cada um. Embaixo de tudo pode ficar o
OpenStreetMap, quando o mapa é real (dá para desligar e mudar a opacidade).

### 3. Linhas

![Linhas](images/lines.jpg)

As linhas e sentidos de `lines.lin` com caixas de seleção, filtros por tipo (ônibus, bonde, metrô, trem) e por dia da semana, a extensão e o tempo de percurso. As linhas marcadas são desenhadas no mapa com suas paradas.

### 4. Horários

![Horários](images/timetables.jpg)

Dos arquivos de horário do próprio mapa (`TTData`): a época (a base ou cada pasta `Chrono`), o dia da semana, a linha, a viagem, as partidas do dia e as paradas de uma viagem com os horários
(estimados pela extensão do trajeto). A viagem escolhida é desenhada no mapa.

### 5. Inspecionar, Anotações, Editar

![Inspecionar](images/inspect.jpg)

- **Inspecionar:** clique no mapa para ver a posição (X Y Z, latitude e longitude nos mapas reais), o tile, o que o pacote diz ali e o que o mapa OMSI 2 diz.
- **Anotações:** marque pontos e áreas como *Errado*, *Melhorar*, *Apagar ao gerar* ou *Conferido*. Ficam guardadas ao lado do pacote (`openomsi-realmap.notes.json`; o jogo nunca lê).
- **Editar:** apagar uma área por classe, pintar uma área, dar nome a uma rua e seu limite de velocidade, apagar uma linha, mover ou apagar um ícone. Cada ação grava o pacote e pode ser desfeita (Ctrl+Z / Ctrl+Y).

### 6. Gerar

![Gerar](images/generate.jpg)

Roda o gerador no mapa associado. Preencha:

| Campo | O que é |
|---|---|
| Pasta do OMSI 2 | a pasta que tem `Maps` e `Vehicles` (só leitura) |
| Modo | `auto` (decide e diz por quê), `exact`, `fitted`, `shore` ou `own` (mapa inventado, sem OpenStreetMap): veja o [README](../README.md#making-a-package) |
| Curvas de nível (m) | o relevo: 1 numa cidade, 5 em morros, 0 para nenhum |
| Norte (graus, modo own) | graus no sentido horário do alto do mapa até o norte real |
| Ponto LAT,LON / Lugar | onde fica a cidade real, para um mapa sem coordenadas |
| Nome do mapa, Tile | o nome no manifesto; o tamanho do tile se não for lido do mapa |
| Servidor Overpass extra, Pausa entre consultas | para servidores do OpenStreetMap ocupados: outro servidor e uma pausa maior |

**Gerar pacote** executa (o log mostra o andamento, e a geração continua se você trocar o idioma ou o tema). O resultado substitui o pacote, com uma cópia em `openomsi-realmap.backups`; **Restaurar cópia** traz uma cópia de volta.

## Teclas

`F` enquadrar · `Q`/`E` girar 15° · `0` norte para cima · `L` mapa claro/escuro · `G` grade de tiles · `N` nomes · `I` ícones · `T` rotas · `R` recarregar · `Ctrl+Z` / `Ctrl+Y` desfazer / refazer.

## Aparência e idiomas

Aparência escura, clara ou a do sistema (Arquivo > Tema). 17 idiomas (Arquivo > Idioma): inglês (EUA, o principal), português (Brasil, Portugal), inglês (Reino Unido), francês, alemão, espanhol
(Espanha, América Latina), italiano, polonês, holandês, russo, chinês (simplificado, tradicional), japonês, húngaro e turco; na primeira vez segue o sistema. As traduções foram feitas com ajuda de uma IA e podem precisar de correções: avise.

## Linha de comando

O mesmo arquivo é o gerador, sem janela:

```
ombr-mapcreator.exe [pasta]                                    abre a janela
ombr-mapcreator.exe gen --omsi "C:/Games/OMSI 2" --map Projekt_Szczecin --mode own --relief 5 --out ./out/szczecin
ombr-mapcreator.exe rails|audit|dedupe|connect|check ...      as outras ferramentas de tools/mapgen, mesmos argumentos
```

## Compatível com

openOMSI, Project Depot e OMSI 2 por meio do OmsiLaunch e do openHUD: veja o [README](../README.md#compatibility).
Este programa é independente e não é afiliado nem endossado por eles nem pelos donos do OMSI 2. É desenvolvido com um parceiro de IA: veja o [AI_DISCLAIMER](../AI_DISCLAIMER.md).
