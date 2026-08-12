/**
 * RAFIKI TFT + SERVOS — Expressions synchronisées avec mouvements
 * Arduino Mega 2560 + shield MCUFRIEND / ILI9486 (480 x 320 paysage)
 *
 * Principes graphiques :
 * - fond bleu nuit uniforme ;
 * - visage centré, sans bordures ni textes parasites ;
 * - traits lumineux simples et cohérents ;
 * - aucune animation continue ;
 * - clignement naturel discret toutes les 3 secondes ;
 * - nettoyage strict de rectangles fixes pour éliminer les résidus ;
 * - vue texte assortie au même langage visuel.
 *
 * Expressions disponibles :
 * 0 HEUREUX
 * 1 CLIN_OEIL
 * 2 TRISTE
 * 3 COLERE
 * 4 NEUTRE
 * 5 AMOUREUX
 * 6 SURPRIS
 * 7 INDIFFERENT
 * 8 RAVI
 * 9 DECU
 *
 * Commandes série supplémentaires :
 * TEXT:Bonjour ! Comment puis-je t'aider aujourd'hui ?
 * SHOW_EYES
 * BLINK
 *
 * Broches recommandées pour les 4 servos sur Mega : 44, 45, 46, 47.
 */

#include <Adafruit_GFX.h>
#include <MCUFRIEND_kbv.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Servo.h>

MCUFRIEND_kbv tft;


// -----------------------------------------------------------------------------
// Servomoteurs - Arduino Mega
// -----------------------------------------------------------------------------
const uint8_t PIN_YL = 44;  // Jambe gauche
const uint8_t PIN_YR = 45;  // Jambe droite
const uint8_t PIN_RL = 46;  // Pied gauche
const uint8_t PIN_RR = 47;  // Pied droit

const int BASE_ANGLE = 0;
const int TRIM_YL = 80;
const int TRIM_YR = 0;
const int TRIM_RL = 0;
const int TRIM_RR = 0;

const float SERVO_SPEED_LIMIT = 100.0f;
const float SERVO_SMOOTHING_TIME = 0.15f;

Servo servoYL;
Servo servoYR;
Servo servoRL;
Servo servoRR;

// 0 repos, 1 YL, 2 YR, 3 RL, 4 RR, 5 séquentiel
uint8_t activeServoTest = 0;

// Comportement synchronisé : -1 = désactivé, 0..9 = expression + mouvement
int8_t activeBehavior = -1;
unsigned long behaviorStartedAt = 0;

float currentServoAngles[4] = {0.0f, 0.0f, 0.0f, 0.0f};
unsigned long lastServoUpdateAt = 0;

// Démonstration écran + servos
bool combinedTestEnabled = false;
unsigned long lastDemoExpressionAt = 0;
uint8_t demoExpressionIndex = 0;
const unsigned long DEMO_EXPRESSION_INTERVAL_MS = 4000;

// -----------------------------------------------------------------------------
// Palette RGB565
// -----------------------------------------------------------------------------
#define C_BG          0x0064   // bleu nuit profond
#define C_CARD        0x08A7   // carte sombre
#define C_CARD_EDGE   0x2250   // contour bleu discret
#define C_CYAN        0x2E7F   // cyan lumineux
#define C_CYAN_SOFT   0x1D7A   // cyan secondaire
#define C_PINK        0xF2B7   // rose lumineux
#define C_RED         0xF249   // rouge émotion
#define C_WHITE       0xFFFF
#define C_TEXT        0xDFFF
#define C_MUTED       0x7C10

const int16_t SCREEN_W = 480;
const int16_t SCREEN_H = 320;

// Zones fixes : chaque redessin efface exactement ces surfaces.
const int16_t LEFT_EYE_ZONE_X  = 72;
const int16_t LEFT_EYE_ZONE_Y  = 72;
const int16_t EYE_ZONE_W       = 136;
const int16_t EYE_ZONE_H       = 112;

const int16_t RIGHT_EYE_ZONE_X = 272;
const int16_t RIGHT_EYE_ZONE_Y = 72;

const int16_t MOUTH_ZONE_X     = 160;
const int16_t MOUTH_ZONE_Y     = 184;
const int16_t MOUTH_ZONE_W     = 160;
const int16_t MOUTH_ZONE_H     = 80;

const int16_t LEFT_X  = 140;
const int16_t RIGHT_X = 340;
const int16_t EYE_Y   = 130;
const int16_t MOUTH_Y = 222;

// Clignement : une fermeture courte, pas d'animation progressive coûteuse.
const unsigned long BLINK_EVERY_MS = 3000;
const unsigned long BLINK_CLOSED_MS = 115;

// -----------------------------------------------------------------------------
// États
// -----------------------------------------------------------------------------
enum ViewMode {
  VIEW_FACE,
  VIEW_TEXT
};

enum Expression {
  HAPPY,
  WINK,
  SAD,
  ANGRY,
  NEUTRAL,
  LOVE,
  SURPRISED,
  INDIFFERENT,
  DELIGHTED,
  DISAPPOINTED
};

ViewMode currentView = VIEW_FACE;
Expression currentExpression = NEUTRAL;

String displayText = "Bonjour ! Comment puis-je t'aider aujourd'hui ?";

unsigned long lastBlinkAt = 0;
unsigned long blinkStartedAt = 0;
bool blinkClosed = false;

// -----------------------------------------------------------------------------
// Outils graphiques
// -----------------------------------------------------------------------------
void thickLine(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint8_t thickness, uint16_t color) {
  int8_t half = thickness / 2;
  for (int8_t i = -half; i <= half; i++) {
    tft.drawLine(x0, y0 + i, x1, y1 + i, color);
  }
  if (half > 0) {
    tft.fillCircle(x0, y0, half, color);
    tft.fillCircle(x1, y1, half, color);
  }
}

void clearEyeZones() {
  tft.fillRect(LEFT_EYE_ZONE_X, LEFT_EYE_ZONE_Y, EYE_ZONE_W, EYE_ZONE_H, C_BG);
  tft.fillRect(RIGHT_EYE_ZONE_X, RIGHT_EYE_ZONE_Y, EYE_ZONE_W, EYE_ZONE_H, C_BG);
}

void clearMouthZone() {
  tft.fillRect(MOUTH_ZONE_X, MOUTH_ZONE_Y, MOUTH_ZONE_W, MOUTH_ZONE_H, C_BG);
}

void clearFaceDynamicZones() {
  clearEyeZones();
  clearMouthZone();
}

void drawGlowDot(int16_t x, int16_t y, uint8_t radius, uint16_t color) {
  tft.fillCircle(x, y, radius + 4, C_CARD);
  tft.fillCircle(x, y, radius + 2, C_CYAN_SOFT);
  tft.fillCircle(x, y, radius, color);
  tft.fillCircle(x - radius / 3, y - radius / 3, max((int)2, (int)radius / 4), C_WHITE);
}

void drawVerticalEye(int16_t x, int16_t y, uint16_t color) {
  tft.fillRoundRect(x - 10, y - 19, 20, 38, 10, C_CARD);
  tft.fillRoundRect(x - 8, y - 17, 16, 34, 8, color);
  tft.fillCircle(x - 3, y - 7, 3, C_WHITE);
}

void drawClosedEye(int16_t x, int16_t y, uint16_t color) {
  thickLine(x - 25, y, x + 25, y, 5, color);
}

void drawHappyEye(int16_t x, int16_t y, uint16_t color) {
  // Arc heureux construit avec deux cercles et un masque de fond.
  tft.drawCircle(x, y + 14, 28, color);
  tft.drawCircle(x, y + 15, 28, color);
  tft.drawCircle(x, y + 16, 28, color);
  tft.fillRect(x - 34, y - 20, 68, 33, C_BG);
}

void drawSadBrow(int16_t x, int16_t y, bool left, uint16_t color) {
  if (left) {
    thickLine(x - 28, y + 4, x + 20, y - 8, 4, color);
  } else {
    thickLine(x - 20, y - 8, x + 28, y + 4, 4, color);
  }
}

void drawAngryBrow(int16_t x, int16_t y, bool left, uint16_t color) {
  if (left) {
    thickLine(x - 28, y - 8, x + 20, y + 5, 6, color);
  } else {
    thickLine(x - 20, y + 5, x + 28, y - 8, 6, color);
  }
}

void drawHeart(int16_t x, int16_t y, uint16_t color) {
  tft.fillCircle(x - 12, y - 8, 13, color);
  tft.fillCircle(x + 12, y - 8, 13, color);
  tft.fillTriangle(x - 25, y - 3, x + 25, y - 3, x, y + 25, color);
  tft.fillCircle(x - 14, y - 12, 4, C_WHITE);
}

void drawSmile(uint16_t color, bool wide = false) {
  int16_t radius = wide ? 36 : 27;
  tft.drawCircle(240, MOUTH_Y - 16, radius, color);
  tft.drawCircle(240, MOUTH_Y - 15, radius, color);
  tft.drawCircle(240, MOUTH_Y - 14, radius, color);
  tft.fillRect(240 - radius - 5, MOUTH_Y - 55, radius * 2 + 10, 38, C_BG);
}

void drawFrown(uint16_t color) {
  tft.drawCircle(240, MOUTH_Y + 22, 23, color);
  tft.drawCircle(240, MOUTH_Y + 23, 23, color);
  tft.drawCircle(240, MOUTH_Y + 24, 23, color);
  tft.fillRect(210, MOUTH_Y + 22, 60, 30, C_BG);
}

void drawFlatMouth(uint16_t color) {
  thickLine(220, MOUTH_Y, 260, MOUTH_Y, 4, color);
}

void drawSmallO(uint16_t color) {
  tft.drawCircle(240, MOUTH_Y, 13, color);
  tft.drawCircle(240, MOUTH_Y + 1, 13, color);
  tft.drawCircle(240, MOUTH_Y + 2, 13, color);
}

void drawFaceBackground() {
  tft.fillScreen(C_BG);

  // Deux halos presque invisibles donnent de la profondeur sans ajouter d'UI.
  tft.drawCircle(LEFT_X, EYE_Y, 58, C_CARD);
  tft.drawCircle(RIGHT_X, EYE_Y, 58, C_CARD);
}

// -----------------------------------------------------------------------------
// Rendu des dix expressions de la référence
// -----------------------------------------------------------------------------
void drawEyesForExpression(Expression expression, bool forcedClosed) {
  clearEyeZones();

  // Un clignement global remplace temporairement les yeux, sauf le clin d'œil.
  if (forcedClosed && expression != WINK) {
    uint16_t blinkColor = (expression == ANGRY) ? C_RED :
                          (expression == LOVE) ? C_PINK : C_CYAN;
    drawClosedEye(LEFT_X, EYE_Y, blinkColor);
    drawClosedEye(RIGHT_X, EYE_Y, blinkColor);
    return;
  }

  switch (expression) {
    case HAPPY:
      drawVerticalEye(LEFT_X, EYE_Y, C_CYAN);
      drawVerticalEye(RIGHT_X, EYE_Y, C_CYAN);
      break;

    case WINK:
      drawClosedEye(LEFT_X, EYE_Y, C_CYAN);
      drawVerticalEye(RIGHT_X, EYE_Y, C_CYAN);
      break;

    case SAD:
      drawSadBrow(LEFT_X, 91, true, C_CYAN);
      drawSadBrow(RIGHT_X, 91, false, C_CYAN);
      drawVerticalEye(LEFT_X, EYE_Y + 5, C_CYAN);
      drawVerticalEye(RIGHT_X, EYE_Y + 5, C_CYAN);
      break;

    case ANGRY:
      drawAngryBrow(LEFT_X, 91, true, C_RED);
      drawAngryBrow(RIGHT_X, 91, false, C_RED);
      tft.fillRoundRect(LEFT_X - 9, EYE_Y - 13, 18, 30, 9, C_RED);
      tft.fillRoundRect(RIGHT_X - 9, EYE_Y - 13, 18, 30, 9, C_RED);
      break;

    case NEUTRAL:
      drawVerticalEye(LEFT_X, EYE_Y, C_CYAN);
      drawVerticalEye(RIGHT_X, EYE_Y, C_CYAN);
      break;

    case LOVE:
      drawHeart(LEFT_X, EYE_Y, C_PINK);
      drawHeart(RIGHT_X, EYE_Y, C_PINK);
      break;

    case SURPRISED:
      drawGlowDot(LEFT_X, EYE_Y - 5, 10, C_CYAN);
      drawGlowDot(RIGHT_X, EYE_Y - 5, 10, C_CYAN);
      break;

    case INDIFFERENT:
      drawClosedEye(LEFT_X, EYE_Y, C_CYAN);
      drawClosedEye(RIGHT_X, EYE_Y, C_CYAN);
      break;

    case DELIGHTED:
      drawHappyEye(LEFT_X, EYE_Y, C_CYAN);
      drawHappyEye(RIGHT_X, EYE_Y, C_CYAN);
      break;

    case DISAPPOINTED:
      drawVerticalEye(LEFT_X, EYE_Y, C_CYAN);
      drawVerticalEye(RIGHT_X, EYE_Y, C_CYAN);
      break;
  }
}

void drawMouthForExpression(Expression expression) {
  clearMouthZone();

  switch (expression) {
    case HAPPY:
      drawSmile(C_CYAN, false);
      break;

    case WINK:
      drawSmile(C_CYAN, false);
      break;

    case SAD:
      drawFrown(C_CYAN);
      break;

    case ANGRY:
      drawFrown(C_RED);
      break;

    case NEUTRAL:
      // volontairement aucune bouche : neutre ultra minimal
      break;

    case LOVE:
      // le visage amoureux se suffit aux yeux en cœur
      break;

    case SURPRISED:
      drawSmallO(C_CYAN);
      break;

    case INDIFFERENT:
      drawFlatMouth(C_CYAN);
      break;

    case DELIGHTED:
      drawSmile(C_CYAN, true);
      break;

    case DISAPPOINTED:
      drawFrown(C_CYAN);
      break;
  }
}

void renderFace(bool forcedClosed = false) {
  if (currentView != VIEW_FACE) return;
  drawEyesForExpression(currentExpression, forcedClosed);

  // La bouche ne bouge pas pendant le clignement : moins de redessin et zéro flash inutile.
  if (!forcedClosed) {
    drawMouthForExpression(currentExpression);
  }
}

// -----------------------------------------------------------------------------
// Vue texte Apple-like
// -----------------------------------------------------------------------------
void drawMiniRobotIcon(int16_t x, int16_t y) {
  tft.fillRoundRect(x - 29, y - 20, 58, 40, 14, C_CARD_EDGE);
  tft.fillRoundRect(x - 25, y - 17, 50, 34, 12, C_BG);
  tft.fillCircle(x - 10, y, 4, C_CYAN);
  tft.fillCircle(x + 10, y, 4, C_CYAN);
}

void drawCenteredText(const char* text, int16_t centerX, int16_t baselineY, uint16_t color, uint8_t size) {
  tft.setFont(&FreeSans9pt7b);
  tft.setTextSize(size);
  tft.setTextColor(color);
  tft.setTextWrap(false);

  int16_t x1 = 0, y1 = 0;
  uint16_t w = 0, h = 0;
  tft.getTextBounds(text, 0, baselineY, &x1, &y1, &w, &h);
  tft.setCursor(centerX - ((int16_t)w / 2) - x1, baselineY);
  tft.print(text);
}

uint16_t measureText(const String& text, uint8_t size) {
  tft.setFont(&FreeSans9pt7b);
  tft.setTextSize(size);
  int16_t x1 = 0, y1 = 0;
  uint16_t w = 0, h = 0;
  tft.getTextBounds(text.c_str(), 0, 0, &x1, &y1, &w, &h);
  return w;
}

void drawWrappedText(String text, int16_t centerX, int16_t firstY, int16_t maxWidth, int16_t lineHeight, uint8_t maxLines, uint8_t size) {
  text.trim();
  if (text.length() == 0) text = "Bonjour !";

  int16_t start = 0;
  uint8_t lineIndex = 0;

  while (start < (int16_t)text.length() && lineIndex < maxLines) {
    while (start < (int16_t)text.length() && text[start] == ' ') start++;

    int16_t end = start;
    int16_t lastSpace = -1;

    while (end < (int16_t)text.length()) {
      if (text[end] == ' ') lastSpace = end;
      String candidate = text.substring(start, end + 1);
      if (measureText(candidate, size) > maxWidth) break;
      end++;
    }

    String line;
    if (end >= (int16_t)text.length()) {
      line = text.substring(start);
      start = text.length();
    } else if (lastSpace >= start) {
      line = text.substring(start, lastSpace);
      start = lastSpace + 1;
    } else {
      int16_t safeEnd = end > start ? end : start + 1;
      line = text.substring(start, safeEnd);
      start = safeEnd;
    }

    line.trim();

    if (lineIndex == maxLines - 1 && start < (int16_t)text.length()) {
      while (line.length() > 3 && measureText(line + "...", size) > maxWidth) {
        line.remove(line.length() - 1);
      }
      line += "...";
      start = text.length();
    }

    drawCenteredText(line.c_str(), centerX, firstY + lineIndex * lineHeight, C_TEXT, size);
    lineIndex++;
  }
}

void drawTextView() {
  currentView = VIEW_TEXT;
  tft.fillScreen(C_BG);

  // Carte centrale, très peu de chrome.
  tft.fillRoundRect(28, 70, 424, 164, 24, C_CARD);
  tft.drawRoundRect(28, 70, 424, 164, 24, C_CARD_EDGE);

  drawMiniRobotIcon(82, 152);

  uint8_t size = displayText.length() <= 35 ? 2 : 1;
  uint8_t lines = size == 2 ? 3 : 5;
  int16_t firstY = size == 2 ? 126 : 112;
  int16_t lineHeight = size == 2 ? 38 : 25;

  drawWrappedText(displayText, 288, firstY, 285, lineHeight, lines, size);

  // Statut compact assorti à la référence.
  tft.fillCircle(190, 274, 6, C_CYAN);
  drawCenteredText("Rafiki est en ligne", 294, 281, C_CYAN, 1);
}

// -----------------------------------------------------------------------------
// Clignement naturel
// -----------------------------------------------------------------------------
void updateBlink() {
  if (currentView != VIEW_FACE) return;

  unsigned long now = millis();

  if (!blinkClosed) {
    if (now - lastBlinkAt >= BLINK_EVERY_MS) {
      blinkClosed = true;
      blinkStartedAt = now;
      renderFace(true);
    }
    return;
  }

  if (now - blinkStartedAt >= BLINK_CLOSED_MS) {
    blinkClosed = false;
    lastBlinkAt = now;
    renderFace(false);
  }
}

void triggerManualBlink() {
  if (currentView != VIEW_FACE || blinkClosed) return;
  blinkClosed = true;
  blinkStartedAt = millis();
  renderFace(true);
}


// -----------------------------------------------------------------------------
// Gestion non bloquante des servomoteurs
// -----------------------------------------------------------------------------
void setServoTest(uint8_t testNumber) {
  if (testNumber > 5) return;
  activeBehavior = -1;
  activeServoTest = testNumber;

  Serial.print(F("SERVO: "));
  if (testNumber == 0) Serial.println(F("REPOS"));
  else if (testNumber == 1) Serial.println(F("JAMBE GAUCHE YL - PIN 44"));
  else if (testNumber == 2) Serial.println(F("JAMBE DROITE YR - PIN 45"));
  else if (testNumber == 3) Serial.println(F("PIED GAUCHE RL - PIN 46"));
  else if (testNumber == 4) Serial.println(F("PIED DROIT RR - PIN 47"));
  else Serial.println(F("SEQUENTIEL"));
}

void calculateServoTargets(float targets[4]) {
  for (uint8_t i = 0; i < 4; i++) {
    targets[i] = (float)BASE_ANGLE;
  }

  unsigned long now = millis();

  // Priorité aux comportements synchronisés écran + mouvements.
  if (activeBehavior >= 0 && activeBehavior <= 9) {
    float t = (now - behaviorStartedAt) / 1000.0f;
    float slow = sin(t * PI);          // période 2 s
    float medium = sin(t * 1.6f * PI); // période ~1,25 s
    float fast = sin(t * 2.4f * PI);   // période ~0,83 s

    switch (activeBehavior) {
      case 0: // HEUREUX : petite danse alternée
        targets[0] = 10.0f + 10.0f * medium;
        targets[1] = 10.0f - 10.0f * medium;
        targets[2] = 7.0f + 7.0f * medium;
        targets[3] = 7.0f - 7.0f * medium;
        break;

      case 1: // CLIN D'OEIL : petit salut de la jambe gauche
        targets[0] = 9.0f + 9.0f * slow;
        targets[2] = 5.0f + 5.0f * slow;
        break;

      case 2: // TRISTE : balancement lent et faible
        targets[0] = 4.0f + 4.0f * slow;
        targets[1] = 4.0f + 4.0f * slow;
        targets[2] = 3.0f;
        targets[3] = 3.0f;
        break;

      case 3: // COLERE : frappe alternée des pieds
        targets[0] = 7.0f;
        targets[1] = 7.0f;
        targets[2] = 10.0f + 10.0f * fast;
        targets[3] = 10.0f - 10.0f * fast;
        break;

      case 4: // NEUTRE : position de repos
        break;

      case 5: // AMOUREUX : balancement doux gauche-droite
        targets[0] = 7.0f + 7.0f * slow;
        targets[1] = 7.0f - 7.0f * slow;
        targets[2] = 4.0f + 4.0f * slow;
        targets[3] = 4.0f - 4.0f * slow;
        break;

      case 6: { // SURPRIS : petit recul simultané puis retour
        float pulse = abs(sin(t * 1.8f * PI));
        targets[0] = 14.0f * pulse;
        targets[1] = 14.0f * pulse;
        targets[2] = 8.0f * pulse;
        targets[3] = 8.0f * pulse;
        break;
      }

      case 7: // INDIFFERENT : quasi immobile
        targets[2] = 2.0f + 2.0f * slow;
        targets[3] = 2.0f - 2.0f * slow;
        break;

      case 8: // RAVI : danse plus énergique
        targets[0] = 12.0f + 12.0f * fast;
        targets[1] = 12.0f - 12.0f * fast;
        targets[2] = 9.0f - 9.0f * fast;
        targets[3] = 9.0f + 9.0f * fast;
        break;

      case 9: // DECU : mouvement lent vers le bas
        targets[0] = 5.0f + 3.0f * slow;
        targets[1] = 5.0f + 3.0f * slow;
        targets[2] = 5.0f + 2.0f * slow;
        targets[3] = 5.0f + 2.0f * slow;
        break;
    }

    for (uint8_t i = 0; i < 4; i++) {
      targets[i] = constrain(targets[i], 0.0f, 24.0f);
    }
    return;
  }

  // Mode de test servo d'origine.
  float phase = (float)(now % 2000UL) / 2000.0f * 2.0f * PI;
  float sweepOffset = 15.0f + 15.0f * sin(phase);

  if (activeServoTest >= 1 && activeServoTest <= 4) {
    targets[activeServoTest - 1] = (float)BASE_ANGLE + sweepOffset;
  } else if (activeServoTest == 5) {
    uint8_t servoIndex = (now / 3000UL) % 4;
    targets[servoIndex] = (float)BASE_ANGLE + sweepOffset;
  }
}

void writeServoByIndex(uint8_t index, int physicalAngle) {
  int finalAngle = physicalAngle;

  if (index == 0) {
    finalAngle += TRIM_YL;
    servoYL.write(constrain(finalAngle, 0, 180));
  } else if (index == 1) {
    finalAngle += TRIM_YR;
    servoYR.write(constrain(finalAngle, 0, 180));
  } else if (index == 2) {
    finalAngle += TRIM_RL;
    servoRL.write(constrain(finalAngle, 0, 180));
  } else {
    finalAngle += TRIM_RR;
    servoRR.write(constrain(finalAngle, 0, 180));
  }
}

void updateServos() {
  unsigned long now = millis();
  float dt = (now - lastServoUpdateAt) / 1000.0f;
  lastServoUpdateAt = now;

  if (dt <= 0.0f) return;
  if (dt > 0.1f) dt = 0.1f;

  float targets[4];
  calculateServoTargets(targets);

  float alpha = dt / (dt + SERVO_SMOOTHING_TIME);
  float maxAngleChange = SERVO_SPEED_LIMIT * dt;

  for (uint8_t i = 0; i < 4; i++) {
    float smoothedTarget = currentServoAngles[i] + alpha * (targets[i] - currentServoAngles[i]);
    float difference = smoothedTarget - currentServoAngles[i];

    if (abs(difference) > maxAngleChange) {
      currentServoAngles[i] += (difference > 0.0f) ? maxAngleChange : -maxAngleChange;
    } else {
      currentServoAngles[i] = smoothedTarget;
    }

    writeServoByIndex(i, round(currentServoAngles[i]));
  }
}

const char* behaviorName(uint8_t behavior) {
  switch (behavior) {
    case 0: return "HEUREUX + DANSE";
    case 1: return "CLIN D'OEIL + SALUT";
    case 2: return "TRISTE + BALANCEMENT LENT";
    case 3: return "COLERE + FRAPPE DES PIEDS";
    case 4: return "NEUTRE + REPOS";
    case 5: return "AMOUREUX + BALANCEMENT DOUX";
    case 6: return "SURPRIS + RECUL";
    case 7: return "INDIFFERENT + MOUVEMENT MINIMAL";
    case 8: return "RAVI + DANSE ENERGIQUE";
    case 9: return "DECU + MOUVEMENT LENT";
    default: return "INCONNU";
  }
}

void setBehavior(uint8_t behavior) {
  if (behavior > 9) return;

  combinedTestEnabled = false;
  activeServoTest = 0;
  activeBehavior = behavior;
  behaviorStartedAt = millis();

  currentExpression = (Expression)behavior;
  currentView = VIEW_FACE;
  blinkClosed = false;
  lastBlinkAt = millis();
  drawFaceBackground();
  renderFace(false);

  Serial.print(F("COMPORTEMENT: "));
  Serial.println(behaviorName(behavior));
}

void stopBehavior() {
  activeBehavior = -1;
  activeServoTest = 0;
  currentExpression = NEUTRAL;
  currentView = VIEW_FACE;
  blinkClosed = false;
  lastBlinkAt = millis();
  drawFaceBackground();
  renderFace(false);
  Serial.println(F("COMPORTEMENT ARRETE - REPOS"));
}

void updateCombinedTest() {
  if (!combinedTestEnabled) return;

  unsigned long now = millis();
  if (now - lastDemoExpressionAt < DEMO_EXPRESSION_INTERVAL_MS) return;

  lastDemoExpressionAt = now;
  demoExpressionIndex = (demoExpressionIndex + 1) % 10;
  currentExpression = (Expression)demoExpressionIndex;
  currentView = VIEW_FACE;
  blinkClosed = false;
  lastBlinkAt = now;
  drawFaceBackground();
  renderFace(false);
}

void startCombinedTest() {
  combinedTestEnabled = true;
  activeBehavior = -1;
  setServoTest(5);
  demoExpressionIndex = 0;
  currentExpression = HAPPY;
  currentView = VIEW_FACE;
  blinkClosed = false;
  lastBlinkAt = millis();
  lastDemoExpressionAt = millis();
  drawFaceBackground();
  renderFace(false);
  Serial.println(F("TEST COMBINE ACTIF : expressions + servos sequentiels"));
}

void stopCombinedTest() {
  combinedTestEnabled = false;
  setServoTest(0);
  currentExpression = NEUTRAL;
  currentView = VIEW_FACE;
  blinkClosed = false;
  lastBlinkAt = millis();
  drawFaceBackground();
  renderFace(false);
  Serial.println(F("TEST COMBINE ARRETE"));
}

// -----------------------------------------------------------------------------
// Commandes série
// -----------------------------------------------------------------------------
void printMenu() {
  Serial.println(F("\n=== RAFIKI V4 APPLE-LIKE ==="));
  Serial.println(F("0 HEUREUX | 1 CLIN_OEIL | 2 TRISTE | 3 COLERE | 4 NEUTRE"));
  Serial.println(F("5 AMOUREUX | 6 SURPRIS | 7 INDIFFERENT | 8 RAVI | 9 DECU"));
  Serial.println(F("Expressions : E0 a E9 ou noms des emotions"));
  Serial.println(F("Servos : S0 repos | S1 YL | S2 YR | S3 RL | S4 RR | S5 sequentiel"));
  Serial.println(F("Comportements synchronises : B0 a B9 | BSTOP pour arreter"));
  Serial.println(F("TEST_ON : ecran + servos | TEST_OFF : arret"));
  Serial.println(F("TEXT:<message> | SHOW_EYES | BLINK"));
}

bool setExpressionFromCommand(String cmd) {
  cmd.toUpperCase();

  if (cmd == "0" || cmd == "HAPPY" || cmd == "HEUREUX") {
    currentExpression = HAPPY;
  } else if (cmd == "1" || cmd == "WINK" || cmd == "CLIN_OEIL" || cmd == "CLIN D'OEIL") {
    currentExpression = WINK;
  } else if (cmd == "2" || cmd == "SAD" || cmd == "TRISTE") {
    currentExpression = SAD;
  } else if (cmd == "3" || cmd == "ANGRY" || cmd == "COLERE" || cmd == "EN COLERE") {
    currentExpression = ANGRY;
  } else if (cmd == "4" || cmd == "NEUTRAL" || cmd == "NEUTRE") {
    currentExpression = NEUTRAL;
  } else if (cmd == "5" || cmd == "LOVE" || cmd == "AMOUREUX") {
    currentExpression = LOVE;
  } else if (cmd == "6" || cmd == "SURPRISED" || cmd == "SURPRIS") {
    currentExpression = SURPRISED;
  } else if (cmd == "7" || cmd == "INDIFFERENT" || cmd == "INDIFFERENT") {
    currentExpression = INDIFFERENT;
  } else if (cmd == "8" || cmd == "DELIGHTED" || cmd == "RAVI") {
    currentExpression = DELIGHTED;
  } else if (cmd == "9" || cmd == "DISAPPOINTED" || cmd == "DECU") {
    currentExpression = DISAPPOINTED;
  } else {
    return false;
  }

  currentView = VIEW_FACE;
  blinkClosed = false;
  lastBlinkAt = millis();
  drawFaceBackground();
  renderFace(false);
  return true;
}

void readSerialCommand() {
  if (Serial.available() <= 0) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) return;

  Serial.print(F("ACK: "));
  Serial.println(cmd);

  String upper = cmd;
  upper.toUpperCase();

  if (upper == "TEST_ON" || upper == "DEMO_ON") {
    startCombinedTest();
    return;
  }

  if (upper == "TEST_OFF" || upper == "DEMO_OFF" || upper == "STOP_ALL") {
    stopCombinedTest();
    return;
  }

  if (cmd.startsWith("TEXT:")) {
    combinedTestEnabled = false;
    displayText = cmd.substring(5);
    displayText.trim();
    drawTextView();
    return;
  }

  if (upper == "SHOW_EYES" || upper == "EYES" || upper == "VISAGE") {
    currentView = VIEW_FACE;
    blinkClosed = false;
    lastBlinkAt = millis();
    drawFaceBackground();
    renderFace(false);
    return;
  }

  if (upper == "BLINK" || upper == "CLIGNER") {
    triggerManualBlink();
    return;
  }

  // Comportements synchronisés : B0..B9.
  if (upper.length() == 2 && upper[0] == 'B' && upper[1] >= '0' && upper[1] <= '9') {
    setBehavior(upper[1] - '0');
    return;
  }

  if (upper == "BSTOP" || upper == "BEHAVIOR_STOP" || upper == "COMPORTEMENT_STOP") {
    stopBehavior();
    return;
  }

  // Commandes servos : S0..S5 ou SERVO:0..SERVO:5
  if ((upper.length() == 2 && upper[0] == 'S' && upper[1] >= '0' && upper[1] <= '5')) {
    combinedTestEnabled = false;
    setServoTest(upper[1] - '0');
    return;
  }

  if (upper.startsWith("SERVO:") && upper.length() >= 7) {
    char value = upper[6];
    if (value >= '0' && value <= '5') {
      combinedTestEnabled = false;
      setServoTest(value - '0');
      return;
    }
  }

  // Commandes écran : E0..E9 ou FACE:0..FACE:9
  if (upper.length() == 2 && upper[0] == 'E' && upper[1] >= '0' && upper[1] <= '9') {
    combinedTestEnabled = false;
    activeBehavior = -1;
    String expressionCommand = String(upper[1]);
    setExpressionFromCommand(expressionCommand);
    return;
  }

  if (upper.startsWith("FACE:") && upper.length() >= 6) {
    char value = upper[5];
    if (value >= '0' && value <= '9') {
      combinedTestEnabled = false;
      String expressionCommand = String(value);
      setExpressionFromCommand(expressionCommand);
      return;
    }
  }

  // Les noms d'émotions restent acceptés.
  if (setExpressionFromCommand(cmd)) {
    combinedTestEnabled = false;
    return;
  }

  Serial.println(F("Commande inconnue."));
  printMenu();
}

// -----------------------------------------------------------------------------
// Arduino
// -----------------------------------------------------------------------------
void drawBootScreen() {
  tft.fillScreen(C_BG);
  drawMiniRobotIcon(240, 125);
  drawCenteredText("RAFIKI", 240, 205, C_TEXT, 2);
  delay(450);
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(25);

  displayText.reserve(180);

  delay(220);

  uint16_t identifier = tft.readID();
  if (identifier == 0xD3D3 || identifier == 0x0000 || identifier == 0xFFFF) {
    identifier = 0x9486;
  }

  tft.begin(identifier);
  tft.setRotation(1);
  tft.setTextWrap(false);

  servoYL.attach(PIN_YL);
  servoYR.attach(PIN_YR);
  servoRL.attach(PIN_RL);
  servoRR.attach(PIN_RR);

  servoYL.write(constrain(BASE_ANGLE + TRIM_YL, 0, 180));
  servoYR.write(constrain(BASE_ANGLE + TRIM_YR, 0, 180));
  servoRL.write(constrain(BASE_ANGLE + TRIM_RL, 0, 180));
  servoRR.write(constrain(BASE_ANGLE + TRIM_RR, 0, 180));
  lastServoUpdateAt = millis();

  drawBootScreen();
  drawFaceBackground();
  renderFace(false);

  lastBlinkAt = millis();
  printMenu();
}

void loop() {
  readSerialCommand();
  updateBlink();
  updateServos();
  updateCombinedTest();
}
