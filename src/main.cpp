#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <DHTesp.h>
#include <time.h>

#include "secrets.h"
#include "emqx_ca.h"


// =====================================================
// BROCHES ESP32
// =====================================================

const int DHT_PIN = 15;
const int VIBRATION_PIN = 34;
const int LED_NORMALE_PIN = 2;
const int LED_ALARME_PIN = 4;


// =====================================================
// TOPICS MQTT
// =====================================================

const char* TOPIC_TEMPERATURE =
    "tdi/moteur/mr01/temperature";

const char* TOPIC_VIBRATION =
    "tdi/moteur/mr01/vibration";

const char* TOPIC_ETAT =
    "tdi/moteur/mr01/etat";

const char* TOPIC_FONCTIONNEMENT =
    "tdi/moteur/mr01/fonctionnement";

const char* TOPIC_ALERTE =
    "tdi/moteur/mr01/alerte";

const char* TOPIC_DISPONIBILITE =
    "tdi/moteur/mr01/disponibilite";

const char* TOPIC_COMMANDE =
    "tdi/moteur/mr01/commande";

const char* TOPIC_COMMANDE_ACK =
    "tdi/moteur/mr01/commande/ack";


// =====================================================
// OBJETS
// =====================================================

DHTesp dhtSensor;

WiFiClientSecure secureClient;
PubSubClient mqttClient(secureClient);


// =====================================================
// TEMPORISATION
// =====================================================

unsigned long dernierEnvoi = 0;

const unsigned long INTERVALLE_ENVOI = 3000;


// =====================================================
// VARIABLES DU MOTEUR
// =====================================================

bool demandeMarche = true;
bool verrouillageSecurite = false;


// =====================================================
// SEUILS DE SURVEILLANCE
// =====================================================

const float TEMP_ATTENTION = 60.0;
const float TEMP_CRITIQUE = 75.0;

const float VIBRATION_ATTENTION = 4.0;
const float VIBRATION_CRITIQUE = 7.0;

const float TEMP_REARMEMENT = 55.0;
const float VIBRATION_REARMEMENT = 3.5;


// =====================================================
// DECLARATIONS ANTICIPEES
// =====================================================

void connecterWiFi();
void synchroniserHeure();
void connecterMQTT();

float lireVibration();

bool mesuresValides(
    float temperature,
    float vibration
);

String determinerEtatSante(
    float temperature,
    float vibration
);

String determinerAlerte(
    const String& etatSante
);

void gererSecurite(
    float temperature,
    float vibration,
    const String& etatSante
);

String determinerFonctionnement();

void commanderLED(
    const String& etatSante,
    const String& fonctionnement
);

void publierErreurCapteur();
void publierDonnees();

void publierAccuseCommande(
    const String& commande,
    const String& resultat,
    const String& raison
);

void recevoirCommande(
    char* topic,
    byte* payload,
    unsigned int length
);


// =====================================================
// CONNEXION WI-FI
// =====================================================

void connecterWiFi()
{
    if (WiFi.status() == WL_CONNECTED)
    {
        return;
    }

    Serial.println();
    Serial.println("Connexion au reseau Wi-Fi...");

    WiFi.mode(WIFI_STA);

    WiFi.begin(
        WIFI_SSID,
        WIFI_PASSWORD,
        6
    );

    unsigned long debutConnexion = millis();

    while (
        WiFi.status() != WL_CONNECTED
        && millis() - debutConnexion < 20000
    )
    {
        Serial.print(".");
        delay(500);
    }

    if (WiFi.status() == WL_CONNECTED)
    {
        Serial.println();
        Serial.println("Wi-Fi connecte.");

        Serial.print("Adresse IP : ");
        Serial.println(WiFi.localIP());
    }
    else
    {
        Serial.println();
        Serial.println(
            "Echec de connexion Wi-Fi."
        );
    }
}


// =====================================================
// SYNCHRONISATION DE L'HEURE POUR TLS
// =====================================================

void synchroniserHeure()
{
    Serial.println();
    Serial.println(
        "Synchronisation de l'heure pour TLS..."
    );

    configTime(
        0,
        0,
        "pool.ntp.org",
        "time.nist.gov"
    );

    time_t maintenant = time(nullptr);
    unsigned long debut = millis();

    while (
        maintenant < 1700000000
        && millis() - debut < 20000
    )
    {
        Serial.print(".");
        delay(500);

        maintenant = time(nullptr);
    }

    Serial.println();

    if (maintenant >= 1700000000)
    {
        Serial.println(
            "Heure synchronisee."
        );
    }
    else
    {
        Serial.println(
            "Avertissement : synchronisation "
            "de l'heure incomplete."
        );
    }
}


// =====================================================
// DETERMINATION DU FONCTIONNEMENT
// =====================================================

String determinerFonctionnement()
{
    if (verrouillageSecurite)
    {
        return "ARRETE_SECURITE";
    }

    if (!demandeMarche)
    {
        return "ARRETE_MANUELLEMENT";
    }

    return "EN_MARCHE";
}


// =====================================================
// PUBLICATION DE L'ACK DE COMMANDE
// =====================================================

void publierAccuseCommande(
    const String& commande,
    const String& resultat,
    const String& raison
)
{
    if (!mqttClient.connected())
    {
        Serial.println(
            "ACK non publie : MQTT deconnecte."
        );

        return;
    }

    String fonctionnement =
        determinerFonctionnement();

    char messageAck[320];

    snprintf(
        messageAck,
        sizeof(messageAck),
        "{"
        "\"commande\":\"%s\","
        "\"resultat\":\"%s\","
        "\"raison\":\"%s\","
        "\"fonctionnement\":\"%s\""
        "}",
        commande.c_str(),
        resultat.c_str(),
        raison.c_str(),
        fonctionnement.c_str()
    );

    /*
     * L'ACK n'est pas conserve par le broker.
     * Retain = false.
     */
    bool publicationReussie =
        mqttClient.publish(
            TOPIC_COMMANDE_ACK,
            messageAck,
            false
        );

    Serial.println();
    Serial.println(
        "===== ACCUSE DE COMMANDE ====="
    );

    Serial.print("Commande : ");
    Serial.println(commande);

    Serial.print("Resultat : ");
    Serial.println(resultat);

    Serial.print("Raison : ");
    Serial.println(raison);

    Serial.print("Fonctionnement : ");
    Serial.println(fonctionnement);

    Serial.print("Message JSON : ");
    Serial.println(messageAck);

    if (publicationReussie)
    {
        Serial.println(
            "ACK publie sur EMQX Cloud."
        );
    }
    else
    {
        Serial.println(
            "Echec de publication de l'ACK."
        );
    }

    Serial.println(
        "================================"
    );
}


// =====================================================
// RECEPTION DES COMMANDES MQTT
// =====================================================

void recevoirCommande(
    char* topic,
    byte* payload,
    unsigned int length
)
{
    String message = "";

    for (unsigned int i = 0; i < length; i++)
    {
        message += (char)payload[i];
    }

    message.trim();
    message.toUpperCase();

    Serial.println();
    Serial.print("Commande recue sur ");
    Serial.print(topic);
    Serial.print(" : ");
    Serial.println(message);

    if (message == "ARRET")
    {
        demandeMarche = false;

        Serial.println(
            "Arret manuel demande et accepte."
        );

        publierAccuseCommande(
            "ARRET",
            "ACCEPTEE",
            "AUCUNE"
        );
    }
    else if (message == "MARCHE")
    {
        if (verrouillageSecurite)
        {
            demandeMarche = false;

            Serial.println(
                "Commande MARCHE refusee."
            );

            Serial.println(
                "Le verrouillage de securite est actif."
            );

            publierAccuseCommande(
                "MARCHE",
                "REFUSEE",
                "VERROUILLAGE_SECURITE"
            );
        }
        else
        {
            demandeMarche = true;

            Serial.println(
                "Commande MARCHE acceptee."
            );

            publierAccuseCommande(
                "MARCHE",
                "ACCEPTEE",
                "AUCUNE"
            );
        }
    }
    else
    {
        Serial.println(
            "Commande MQTT inconnue."
        );

        publierAccuseCommande(
            message,
            "REFUSEE",
            "COMMANDE_INCONNUE"
        );
    }
}


// =====================================================
// CONNEXION MQTT SECURISEE
// =====================================================

void connecterMQTT()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        return;
    }

    while (!mqttClient.connected())
    {
        Serial.println();
        Serial.println(
            "Connexion TLS au broker EMQX Cloud..."
        );

        bool connexionReussie =
            mqttClient.connect(
                MQTT_CLIENT_ID,
                MQTT_USERNAME,
                MQTT_PASSWORD,
                TOPIC_DISPONIBILITE,
                1,
                true,
                "OFFLINE"
            );

        if (connexionReussie)
        {
            Serial.println(
                "Connexion MQTT TLS reussie."
            );

            Serial.print("Broker : ");
            Serial.println(MQTT_SERVER);

            Serial.print("Port TLS : ");
            Serial.println(MQTT_PORT);

            Serial.print("Client ID : ");
            Serial.println(MQTT_CLIENT_ID);

            Serial.print("Username : ");
            Serial.println(MQTT_USERNAME);

            bool onlinePublie =
                mqttClient.publish(
                    TOPIC_DISPONIBILITE,
                    "ONLINE",
                    true
                );

            if (onlinePublie)
            {
                Serial.println(
                    "Disponibilite ONLINE publiee."
                );
            }
            else
            {
                Serial.println(
                    "Echec de publication ONLINE."
                );
            }

            bool abonnementReussi =
                mqttClient.subscribe(
                    TOPIC_COMMANDE,
                    1
                );

            if (abonnementReussi)
            {
                Serial.print(
                    "Abonnement securise au topic : "
                );

                Serial.println(
                    TOPIC_COMMANDE
                );
            }
            else
            {
                Serial.println(
                    "Echec abonnement au topic commande."
                );
            }
        }
        else
        {
            Serial.print(
                "Connexion MQTT TLS echouee. Code : "
            );

            Serial.println(
                mqttClient.state()
            );

            Serial.println(
                "Nouvelle tentative dans 5 secondes."
            );

            delay(5000);
        }
    }
}


// =====================================================
// LECTURE DE LA VIBRATION
// =====================================================

float lireVibration()
{
    int valeurAnalogique =
        analogRead(VIBRATION_PIN);

    float vibration =
        (
            valeurAnalogique
            / 4095.0
        )
        * 10.0;

    return vibration;
}


// =====================================================
// VALIDATION DES MESURES
// =====================================================

bool mesuresValides(
    float temperature,
    float vibration
)
{
    if (isnan(temperature))
    {
        return false;
    }

    if (
        temperature < -20.0
        || temperature > 150.0
    )
    {
        return false;
    }

    if (
        vibration < 0.0
        || vibration > 10.0
    )
    {
        return false;
    }

    return true;
}


// =====================================================
// DETERMINATION DE L'ETAT DE SANTE
// =====================================================

String determinerEtatSante(
    float temperature,
    float vibration
)
{
    if (
        temperature > TEMP_CRITIQUE
        || vibration > VIBRATION_CRITIQUE
    )
    {
        return "CRITIQUE";
    }

    if (
        temperature > TEMP_ATTENTION
        || vibration > VIBRATION_ATTENTION
    )
    {
        return "ATTENTION";
    }

    return "NORMAL";
}


// =====================================================
// DETERMINATION DE L'ALERTE
// =====================================================

String determinerAlerte(
    const String& etatSante
)
{
    if (etatSante == "CRITIQUE")
    {
        return "ANOMALIE_CRITIQUE";
    }

    if (etatSante == "ATTENTION")
    {
        return "AVERTISSEMENT";
    }

    return "AUCUNE_ALERTE";
}


// =====================================================
// GESTION DE LA SECURITE
// =====================================================

void gererSecurite(
    float temperature,
    float vibration,
    const String& etatSante
)
{
    if (etatSante == "CRITIQUE")
    {
        if (!verrouillageSecurite)
        {
            Serial.println();
            Serial.println(
                "ANOMALIE CRITIQUE DETECTEE."
            );

            Serial.println(
                "Arret automatique de securite."
            );
        }

        verrouillageSecurite = true;
        demandeMarche = false;

        return;
    }

    if (
        verrouillageSecurite
        && temperature < TEMP_REARMEMENT
        && vibration < VIBRATION_REARMEMENT
    )
    {
        verrouillageSecurite = false;

        Serial.println();
        Serial.println(
            "Les conditions sont redevenues sures."
        );

        Serial.println(
            "Verrouillage de securite retire."
        );

        Serial.println(
            "Une commande MARCHE est necessaire."
        );
    }
}


// =====================================================
// COMMANDE DES LED
// =====================================================

void commanderLED(
    const String& etatSante,
    const String& fonctionnement
)
{
    bool fonctionnementNormal =
        etatSante == "NORMAL"
        && fonctionnement == "EN_MARCHE";

    if (fonctionnementNormal)
    {
        digitalWrite(
            LED_NORMALE_PIN,
            HIGH
        );

        digitalWrite(
            LED_ALARME_PIN,
            LOW
        );
    }
    else
    {
        digitalWrite(
            LED_NORMALE_PIN,
            LOW
        );

        digitalWrite(
            LED_ALARME_PIN,
            HIGH
        );
    }
}


// =====================================================
// ERREUR CAPTEUR
// =====================================================

void publierErreurCapteur()
{
    Serial.println();
    Serial.println(
        "Erreur : mesure capteur invalide."
    );

    verrouillageSecurite = true;
    demandeMarche = false;

    mqttClient.publish(
        TOPIC_ETAT,
        "ERREUR_CAPTEUR",
        true
    );

    mqttClient.publish(
        TOPIC_FONCTIONNEMENT,
        "ARRETE_SECURITE",
        true
    );

    mqttClient.publish(
        TOPIC_ALERTE,
        "DONNEE_INVALIDE",
        true
    );

    commanderLED(
        "CRITIQUE",
        "ARRETE_SECURITE"
    );
}


// =====================================================
// PUBLICATION DES DONNEES
// =====================================================

void publierDonnees()
{
    if (!mqttClient.connected())
    {
        return;
    }

    TempAndHumidity donneesDHT =
        dhtSensor.getTempAndHumidity();

    float temperature =
        donneesDHT.temperature;

    float vibration =
        lireVibration();

    if (
        !mesuresValides(
            temperature,
            vibration
        )
    )
    {
        publierErreurCapteur();
        return;
    }

    String etatSante =
        determinerEtatSante(
            temperature,
            vibration
        );

    gererSecurite(
        temperature,
        vibration,
        etatSante
    );

    String fonctionnement =
        determinerFonctionnement();

    String alerte =
        determinerAlerte(
            etatSante
        );

    commanderLED(
        etatSante,
        fonctionnement
    );

    char temperatureTexte[12];
    char vibrationTexte[12];

    dtostrf(
        temperature,
        1,
        2,
        temperatureTexte
    );

    dtostrf(
        vibration,
        1,
        2,
        vibrationTexte
    );

    /*
     * Mesures périodiques :
     * Retain désactivé.
     */
    mqttClient.publish(
        TOPIC_TEMPERATURE,
        temperatureTexte,
        false
    );

    mqttClient.publish(
        TOPIC_VIBRATION,
        vibrationTexte,
        false
    );

    /*
     * Derniers états conservés par le broker.
     */
    mqttClient.publish(
        TOPIC_ETAT,
        etatSante.c_str(),
        true
    );

    mqttClient.publish(
        TOPIC_FONCTIONNEMENT,
        fonctionnement.c_str(),
        true
    );

    mqttClient.publish(
        TOPIC_ALERTE,
        alerte.c_str(),
        true
    );

    Serial.println();
    Serial.println(
        "===== DONNEES DU MOTEUR ====="
    );

    Serial.print(
        "Temperature : "
    );

    Serial.print(
        temperature,
        2
    );

    Serial.println(
        " degres C"
    );

    Serial.print(
        "Vibration : "
    );

    Serial.print(
        vibration,
        2
    );

    Serial.println(
        " mm/s"
    );

    Serial.print(
        "Etat de sante : "
    );

    Serial.println(
        etatSante
    );

    Serial.print(
        "Fonctionnement : "
    );

    Serial.println(
        fonctionnement
    );

    Serial.print(
        "Alerte : "
    );

    Serial.println(
        alerte
    );

    Serial.print(
        "Verrouillage securite : "
    );

    if (verrouillageSecurite)
    {
        Serial.println("ACTIF");
    }
    else
    {
        Serial.println("INACTIF");
    }

    Serial.println(
        "Donnees publiees sur EMQX Cloud TLS."
    );

    Serial.println(
        "=============================="
    );
}


// =====================================================
// SETUP
// =====================================================

void setup()
{
    Serial.begin(115200);

    pinMode(
        LED_NORMALE_PIN,
        OUTPUT
    );

    pinMode(
        LED_ALARME_PIN,
        OUTPUT
    );

    pinMode(
        VIBRATION_PIN,
        INPUT
    );

    digitalWrite(
        LED_NORMALE_PIN,
        LOW
    );

    digitalWrite(
        LED_ALARME_PIN,
        LOW
    );

    dhtSensor.setup(
        DHT_PIN,
        DHTesp::DHT22
    );

    connecterWiFi();

    if (WiFi.status() == WL_CONNECTED)
    {
        synchroniserHeure();
    }

    /*
     * Vérification du certificat du broker EMQX.
     * Ne pas remplacer par setInsecure().
     */
    secureClient.setCACert(
        EMQX_ROOT_CA
    );

    mqttClient.setServer(
        MQTT_SERVER,
        MQTT_PORT
    );

    mqttClient.setCallback(
        recevoirCommande
    );

    mqttClient.setKeepAlive(60);
    mqttClient.setSocketTimeout(15);
    mqttClient.setBufferSize(512);

    connecterMQTT();
}


// =====================================================
// LOOP
// =====================================================

void loop()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        connecterWiFi();

        if (WiFi.status() == WL_CONNECTED)
        {
            synchroniserHeure();
        }
    }

    if (!mqttClient.connected())
    {
        connecterMQTT();
    }

    mqttClient.loop();

    unsigned long tempsActuel =
        millis();

    if (
        tempsActuel - dernierEnvoi
        >= INTERVALLE_ENVOI
    )
    {
        dernierEnvoi = tempsActuel;

        publierDonnees();
    }

    delay(10);
}