"""patterns.py - what a scenery object or spline IS, from the words of its file path (nothing else in a tile says so).

Authors name their files in their own language and folders. The words below were gathered from the packs that come with
OMSI 2 (German, English, Polish) and from real maps (Brigadeiro Sampaio: Portuguese; folders such as "vegetacoes/arvores",
files such as "mato3", "grass_12", "plt0013x", "casa_mod6"), and derived into Spanish, French, Polish, German, Portuguese
and English. Accents are dropped before matching (arvore = arvore = arbre), so only the plain letters are listed.

A path is cut into words (letters and digits); a word counts when it equals an entry, or starts with an entry that ends
with `*`. An entry with `_` is a run of words (`car_park`). The file name is tried before the folders, and in each the
first category that has a word wins, in the order of PRIORITY: a pole in a folder called "vegetation" is a pole.

    classify("sceneryobjects/brigadeiro/mato3.sco")  ->  "grass"
"""
import functools
import re
import unicodedata

# category -> words
WORDS = {
    # things that are no area: furniture, signs, wires, people, animals, markings, stops of vehicles
    "other": """pole* poste* postes* mast* mastro* masto* sign* signal* schild* placa* placas* panneau* panel* senal* znak* znaki*
        light* lamp* luz* lumin* farol* fanal* lampa* latarn* lanterne* luminaire*
        busstop haltestelle* parada* paragem* przystan* arret* ponto* point* stop* zatoka* shelter* abrigo* wiata*
        fence* zaun* cerca* cercado* vallado* valla* ograd* cloture* barriere* barreira* barrera* barrier* guard* grade* grille*
        bench* banc trash* lixo* lixeira* basura* ordures* poubelle* smiec* mull* muell* abfall* container* conteiner*
        car_park* parking* parqueo* estaciona* stationnement* parkplatz* parkow*
        people* human* pessoa* pessoas* personas* personne* ludzie* ludz* menschen* pedestre* passant* pieton* pieszy*
        traffic* trafego* transito* trafic* semaforo* ampel* sygnaliz* wall* mauer* muro* muros* mur murs mury*
        kabel* wire* cabo* cabos* cable* cables* przewod* rede* catenar* oberleitung* fahrdraht* trolebus* trolleybus* hochspann*
        routearrow* routearrows* itinerario* itineraire* seta* setas* arrow* pfeil* fleche* strzalk* flecha*
        lombada* olho* speedbump* schwelle* ralentisseur* cone cones hydrant* hidrante* bouche*
        fireworks* firework* boi vaca vacas vaches cow* horse* cavalo* caballo* cheval* pferd* kuh* konie* krowa* animal* animais* animaux* tier*
        entrypoint* spawn* marker* marcador* marcacao* marcaje* marquage* markierung* oznacz*
        sprite* decal* sombra* shadow* ombre* schatten* cross* faixa* zebra* passadeira* przejscie*
        sodium* slup* barierk* sidewalk* chodnik* calcada* acera* trottoir* gehweg* rocha* rochas* pedra* pedras* stein* rock* rocks* roche* skala* skaly* piedra* morro* serra* serras* neon* strlt* whip* troll* lbl* catraca* mourao* asfalto* asphalt* recapamento* buraco* pothole* truck* carro* carros* veiculo* veiculos* vehicle* vehicles* fahrzeug* voiture* coche* camion* bus_ onibus* lombadas* antena* antenna* antenne* billboard* outdoor* mupi* painel* cartaz* plakat* werbung* publicite* reklama*""",
    "water": """wasser* water* woda* wody* rzek* river* rio rios riacho* arroio* arroyo* ruisseau* riviere* fleuve* fluss* bach*
        lake* lago lagos lagoa* lagune* laguna* lac lacs jezior* staw* teich* pond* estanque* etang* mar mare represa* acude* embalse* barrage* talsperre*
        sea meer* morze* canal* kanal* kanaly* fountain* fonte fontes fontaine* fuente* brunnen* fontanna* piscina* pool* schwimm* basen* swimming* stream* creek*""",
    "sport": """stadion* stadium* estadio* stade* stadio* boisko* pitch* futebol* fussball* football* futbol* pilka* tennis* tenis* quadra*
        cancha* spielplatz* playground* parquinho* plac_zabaw aire_jeux basketball* basquete* baloncesto* basket* koszyk*
        sport* esporte* deporte* arena* ginasio* gimnasio* gymnase* skate* atletismo*""",
    "built": """haus* house* houses* home* casa casas casinha* casebre* sobrado* barraco* favela* maison* pavillon* villa* villas* dom domy domek* domki* chata*
        gebaeude* building* buildings* edific* edifice* edificio* predio* predios* immeuble* batiment* budynek* budynki* bud kamienic* blok bloki* block* blocks* bloque* bloc
        wohn* resid* residenc* hochhaus* plattenbau* hoch* row* reihen* apartament* apartment* apartamento* appartement* condomin* hlm wiezowiec* drapacz*
        halle* hall hallen hala* hale* galpao* galpon* nave entrepot* depot* depo* magazyn* almacen* armazem* warehouse* lager* bodega* hangar*
        fabr* factory* fabrica* usine* zaklad* fabryka* industr* gewerb* comerc* commerc* sklep* loja* lojas* tienda* tiendas* magasin* boutique* laden* shop* shops* store stores* mercado* market* supermerc* markt* targ*
        garage* garagem* garagen* garaz* garaje* cochera* box01 workshop* oficina* taller* atelier* werkstatt* warsztat*
        church* kirche* igreja* iglesia* eglise* kosciol* kaplica* chapel* capela* capilla* chapelle* templo* temple* tempel* synagog* mosque* mesquita* mezquita*
        school* schule* schul* escola* colegio* escuela* ecole* szko* faculdade* universid* universit* hospital* klinik* clinic* clinica* szpital* creche* kindergarten* przedszk*
        hotel* hostel* pousada* posada* motel* mall* shopping* terminal* dworzec* bahnhof* gare estacao* estacion* station* tower* turm* torre* tour wieza* office* buro* bureau* oficin* biuro* escritorio*
        rathaus* prefeitura* ayuntamiento* mairie* urzad* ratusz* police* policia* delegacia* komisariat* bombeiro* feuerwehr* pompier* straz*
        brick* brk* redbrk* storey* stry* detached* detatched* semidet* terraced* townhouse* cottage* bungalow* chalet* cabin* cabana* hut hutte* schuppen* shed* barn* scheune* celeiro* galinheiro* estabulo* posto tankstelle* gasolin* stacja* petrol*
        museum* museu* museo* musee* muzeum* teatro* theater* theatre* teatr* cinema* kino* biblioteca* library* bibliotheque* bibliothek* biblioteka* banque* bank cobertura* telhado* roof* dach* toit* techo*""",
    "farm": """acker* feld felder field fields campo campos champ champs pola* uprawa* uprawy* cultivo* cultivos* lavoura* plantacao* plantacion* plantation* plantage* plantaci*
        haybale* hay* heu* foin* fieno* siano* balles* farm* fazenda* granja* ferme* gospodarstwo* hacienda* rancho* ranch* crop* crops* getreide* weizen* trigo ble pszeni* rzepak* colza* canola* cevada* orzo* gerste* jecz* kukurydz*
        milho* maiz* corn* maize* soja* soy* soybean* cana canavial* cafe cafezal* coffee* algodao* algodon* coton* bawelna* batata* patata* ziemniak* tomate* tomato* pomidor* horta* huerta* huerto* potager*
        vinha* vinedo* vigne* weinberg* winnica* vineyard* pasto* pastagem* pasture* pastizal* paturage* weide* pastwisk* arroz* rice* riz reis cultivated* agricol* agrar* rolnic* landwirt*""",
    "forest": """tree* trees* baum* baeume* arbor* arbre* arbres* arbol* arboles* arv arvore* arvores* drzew* wood woods forest* forst* wald* walder* bois bosque* bosques* floresta* florestas* foret* forets* las lasy lesn* selva* mata jungle* jungla* dschungel*
        pine* pinus* pino* pinho* pinheiro* pin sapin* sosna* sosn* kiefer* fichte* tanne* fir spruce* abeto* abies* swierk* jodla* oak* eiche* roble* encina* chene* dab deb* quercus* carvalho*
        birch* birke* bouleau* bedul* abedul* bidoeiro* brzoz* lipa linde* tilleul* tilo tilia* wierzb* salgueiro* sauce* saule* topol* pappel* poplar* alamo* peuplier* choupo* buk buche* hetre* haya* faia* beech*
        palm* palme* palmen* palmier* palmeira* palmera* coqueiro* coconut* buriti* carnauba* bambu* bamboo* bambus* bambou* eucalipt* eucalyp* acacia* akacj* cipres* cypress* cypr* zypress* cedro* cedar* cedre* zeder* mangueira* jaqueira* ipe oiti sibipiruna* ficus* figueira* tipuana*
        shrub* busch* bush* bushes* arbust* arbusto* arbuste* krzew* strauch* hedge* hecke* haie* haies* seto setos sebe* zywoplot* zywopl* moita* touffe* thicket* gehoelz* sotobosque* underwood* capoeira* cerrado* caatinga* restinga* mangue* mangrove* manglar*
        laub* nadel* conifer* conifere* coniferas* iglast* lisc* eukalyptus* obst* fruit* fruta frutal* frutas* owoc* verger* pomar* apfel* pomme pommier* laranjeira* naranjo* citrus* limoeiro* limao citronnier*
        arvoredo* alameda* allee* alley* aleja* bosquete* boschetto* kepa* zagajnik* gaj lund*""",
    "grass": """grass* gras* rasen* wiese* wiesen* meadow* prairie* pradera* prado* pradaria* pelouse* herbe* herbes* gazon* cesped* hierba* hierbas* grama* gramado* gramas* relva* capim* capins* campina* trawa* trawy* trawnik* laka laki
        scrub* mato* matagal* matagais* maquis* garrigue* matorral* matorrales* zarosla* zarosl* krzak* heide* heath* bruyere* brezo* brejo* varzea* pantano* sumpf* moor* marais* bagno* torfowisko*
        plt* planta* plantas* plant* plants* pflanze* pflanzen* plante* plantes* roslin* flor flores* flower* flowers* blume* blumen* fleur* fleurs* kwiat* kwiaty* erva ervas* weed* weeds* unkraut* chwast*
        veget* wegetac* lawn* garden* jardim* jardins* jardin* garten* ogrod* parque* park* parc parcs parki* areaverde* zielen* zielone* gruenflaeche*
        musgo* moss* moos* mousse* mech* samambaia* fern* farn* fougere* paproc* ornamental* canteiro* beet* massif* rabatka* floreira* tapete*""",
}

PRIORITY = ["other", "water", "sport", "built", "farm", "forest", "grass"]


def norm(s):
    """Lower case, accents dropped: 'Arvore/Foret/Zywoplot' from 'Árvore/Forêt/Żywopłot'."""
    s = s.lower().replace("ł", "l").replace("ø", "o").replace("ß", "ss").replace("æ", "ae").replace("œ", "oe")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _compile(words):
    exact, prefix, phrases = set(), [], []
    for w in words.split():
        w = norm(w)
        if "_" in w and not w.endswith("*"):
            phrases.append(" " + w.replace("_", " ") + " ")
        elif "_" in w:
            phrases.append(" " + w[:-1].replace("_", " "))
        elif w.endswith("*"):
            prefix.append(w[:-1])
        else:
            exact.add(w)
    return exact, tuple(sorted(set(prefix))), tuple(phrases)


_COMPILED = {k: _compile(v) for k, v in WORDS.items()}


def tokens(path):
    return [t for t in re.split(r"[^a-z0-9]+", norm(path)) if t]


def _hit(cat, group):
    exact, prefix, phrases = _COMPILED[cat]
    joined = " " + " ".join(group) + " "
    for p in phrases:
        if p in joined:
            return p.strip()
    for t in group:
        if t in exact or (prefix and t.startswith(prefix)):
            return t
    return None


def explain(path):
    """(category, the word that decided) of a scenery object path; ('', '') when no word is known. The file name counts
    before the folders: a tree in a folder of buildings is a tree."""
    name = tokens(path.replace("\\", "/").rsplit("/", 1)[-1])
    for group in (name, tokens(path)):
        for cat in PRIORITY:
            w = _hit(cat, group)
            if w:
                return cat, w
    return "", ""


@functools.lru_cache(maxsize=None)
def classify(path):
    """'other', 'water', 'sport', 'built', 'farm', 'forest' or 'grass' for a scenery object path; '' when no word is known."""
    return explain(path)[0]


# words of a spline file (the .sli path): rails and water courses, in the same languages
RAIL_WORDS = r"rail|gleis|tram|szyn|schiene|\btor\b|track|ferrovi|trilho|ferrocarril|riel|voie_fer|chemin_de_fer|kolej|bonde|vlt|metro"
NOT_RAIL_WORDS = r"odciag|catenary|catenaria|oberleitung|fahrdraht|wire|mast|sleeper|dormente|bed|schotter|ballast|lastro|balasto"
WATER_SPLINE_WORDS = (r"river|fluss|bach\b|rzek|canal|kanal|woda|water|wasser|stream|\brio\b|riacho|arroio|arroyo|corrego|ruisseau|"
                      r"riviere|potok|strumien|rzeka")
