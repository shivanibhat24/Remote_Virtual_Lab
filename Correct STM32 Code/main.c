/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body — FULLY FIXED VERSION (BugBuster 3.0)
  *
  * Complete Bug Fix Log:
  * ── Round 1 (Logical Errors in main loop & parse_command) ──────────────────
  *  FIX-01: ADC channels were swapped. Multimeter uses CH0 (PA0), Boost uses CH1 (PA1)
  *  FIX-02: Temperature sent every 2000ms; corrected to 1000ms per problem spec
  *  FIX-03: Ammeter mode char was lowercase 'a'; corrected to 'A'
  *  FIX-04: Parabolic wave string was "pa" (lowercase); corrected to "PA"
  *  FIX-05: VREG strncmp length was 12; corrected to 8 (strlen("#VREG:V="))
  *  FIX-06: VREG duty used integer division (v/12 = 0 for v<12); fixed to float
  *  FIX-07: No 85% duty cycle hard cap on Boost PWM; added BOOST_MAX_DUTY clamp
  *  FIX-08: Boost voltage scaling used *4.0 (overcalculates); corrected to *3.636f
  *  FIX-09: ADC init sampling time was 1CYCLE_5 (too fast); corrected to 55CYCLES_5
  *
  * ── Round 2 (Deeper Logical Errors) ────────────────────────────────────────
  *  FIX-10: Ground mode ('G') still read ADC and sent live data; now sends 0.0f
  *  FIX-11: DSO mode sent 100 individual USB packets/sec causing overflow;
  *           now batches DSO_BATCH_SIZE samples before transmitting
  *  FIX-12: pulse_count sent raw to GUI as temperature; converted to °C via
  *           Kelvin offset (pulse_count = frequency Hz = Kelvin from VCO scaling)
  *  FIX-13: f=0 in WAVE:F command was unhandled (no ACK, generator wouldn't stop);
  *           now explicitly stops TIM2 output and sends ACK
  *  FIX-14: usb_rx_buffer had no null-termination or length guard;
  *           fixed in CDC_Receive callback (see usbd_cdc_if.c note below)
  *  FIX-15: 7-segment displayed raw pulse_count, not converted temperature;
  *           now uses same temp_celsius conversion as TASK 4
  *  FIX-16: TIM2 prescaler APB1 doubling dependency documented explicitly
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usb_device.h"

/* USER CODE BEGIN Includes */
#include "usbd_cdc_if.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
/* USER CODE END Includes */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;
TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;

/* USER CODE BEGIN PV */

// ── USB ─────────────────────────────────────────────────────────────────────
// NOTE (FIX-14): null-termination is applied in usbd_cdc_if.c CDC_Receive_FS:
//   uint32_t len = Len > 63 ? 63 : Len;
//   memcpy(usb_rx_buffer, Buf, len);
//   usb_rx_buffer[len] = '\0';
//   usb_data_ready = 1;
char usb_rx_buffer[64];
uint8_t usb_data_ready = 0;

// ── Counter / Mode ───────────────────────────────────────────────────────────
// pulse_count: VCO pulses counted during 555 gate window.
// VCO scaling: LM335 → 10mV/°K → VCO → 1 Hz/°K (adjust VCO_HZ_PER_KELVIN if needed)
#define VCO_HZ_PER_KELVIN   1.0f   // ← tune this to match your VCO circuit
#define KELVIN_OFFSET       273.15f

volatile uint32_t pulse_count    = 0;
volatile uint8_t  counting_active = 0;
char  current_mode    = 'V';    // 'V'=Voltmeter, 'A'=Ammeter, 'D'=DSO, 'G'=Ground
float volt_multiplier = 12.0f;

// ── Task Timing ──────────────────────────────────────────────────────────────
uint32_t tick_10ms   = 0;
uint32_t tick_500ms  = 0;
uint32_t tick_1000ms = 0;   // FIX-02: was tick_2000ms
uint32_t tick_3ms    = 0;

// ── 7-Segment (Common Cathode) ───────────────────────────────────────────────
// Segment mapping: PB1=a, PB10=b, PB11=c, PB12=d, PB13=e, PB14=f, PB15=g
uint8_t  digit_map[10]  = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F};
uint16_t seg_pins[7]    = {GPIO_PIN_1, GPIO_PIN_10, GPIO_PIN_11, GPIO_PIN_12,
                            GPIO_PIN_13, GPIO_PIN_14, GPIO_PIN_15};
int current_digit_idx = 0;

// ── DSO Batch Buffer (FIX-11) ────────────────────────────────────────────────
#define DSO_BATCH_SIZE  10
static float    dso_buffer[DSO_BATCH_SIZE];
static uint8_t  dso_idx = 0;

// ── Boost PWM Constraint (FIX-07) ────────────────────────────────────────────
// TIM1 ARR = 359  →  200 kHz @ 72 MHz, prescaler = 0
// 85% of 359 = 305.15  →  floor to 305
#define BOOST_ARR       359U
#define BOOST_MAX_DUTY  305U    // 305/359 = 84.96% < 85% hard limit

// ── Function Prototypes ───────────────────────────────────────────────────────
void     parse_command(char* buf);
uint32_t get_adc_value(uint32_t channel);
float    get_temperature_celsius(void);

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_ADC1_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);

/* ============================================================================
 * MAIN
 * ========================================================================== */
int main(void)
{
    HAL_Init();
    SystemClock_Config();

    MX_GPIO_Init();
    MX_ADC1_Init();
    MX_TIM1_Init();
    MX_TIM2_Init();
    MX_TIM3_Init();
    MX_USB_DEVICE_Init();

    /* USER CODE BEGIN 2 */

    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_3);

    // TIM1: 200 kHz boost gate driver, initial duty 66.8% (well under 85%)
    __HAL_TIM_SET_AUTORELOAD(&htim1, BOOST_ARR);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, 240);

    // TIM2: Function generator, initial 280 Hz, 50% duty
    // FIX-16: TIM2 on APB1 (36 MHz bus). Because APB1 prescaler != 1, STM32
    //         doubles the timer clock → TIM2 clock = 72 MHz.
    //         Prescaler = 71 → timer ticks at 72MHz/72 = 1 MHz. Correct.
    __HAL_TIM_SET_AUTORELOAD(&htim2, 3570);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, 1785);

    // TIM3: Voltage regulator PWM, 20 kHz, initially 0 V output
    __HAL_TIM_SET_AUTORELOAD(&htim3, 3599);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, 0);

    // Initial range: 12 V  (PA6=1, PA7=1)
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_SET);

    /* USER CODE END 2 */

    /* ── Infinite Loop ─────────────────────────────────────────────────── */
    while (1)
    {
        /* ── TASK 1: USB Command Parsing ──────────────────────────────── */
        if (usb_data_ready) {
            parse_command(usb_rx_buffer);
            usb_data_ready = 0;
        }

        /* ── TASK 2: Multimeter / DSO Data — 10 ms — PA0 (CH0) ────────── */
        // FIX-01: Was ADC_CHANNEL_1 (PA1). PA0 = ADC_CHANNEL_0.
        if (HAL_GetTick() - tick_10ms >= 10) {
            tick_10ms = HAL_GetTick();

            float val = 0.0f;

            // FIX-10: Ground mode must output 0.0 (calibration reference),
            //         not a live ADC reading.
            if (current_mode == 'G') {
                val = 0.0f;
                char msg[40];
                sprintf(msg, "#DATA:M=%c,X=%.2f;\r\n", current_mode, val);
                CDC_Transmit_FS((uint8_t*)msg, strlen(msg));
            }
            // FIX-11: DSO mode batches samples to avoid 100 packets/sec USB flood.
            else if (current_mode == 'D') {
                uint32_t raw = get_adc_value(ADC_CHANNEL_0);
                val = (raw / 4095.0f) * volt_multiplier;
                dso_buffer[dso_idx++] = val;

                if (dso_idx >= DSO_BATCH_SIZE) {
                    // Build one packet with all samples: #DSO:v0,v1,...,v9;
                    char msg[256];
                    int  pos = 0;
                    pos += sprintf(msg + pos, "#DSO:");
                    for (int i = 0; i < DSO_BATCH_SIZE; i++) {
                        pos += sprintf(msg + pos, "%.2f", dso_buffer[i]);
                        if (i < DSO_BATCH_SIZE - 1) msg[pos++] = ',';
                    }
                    pos += sprintf(msg + pos, ";\r\n");
                    CDC_Transmit_FS((uint8_t*)msg, (uint16_t)pos);
                    dso_idx = 0;
                }
            }
            // Voltmeter and Ammeter modes
            else {
                uint32_t raw = get_adc_value(ADC_CHANNEL_0);
                // FIX-03: Was 'a' (lowercase). GUI sends 'A' for Ammeter.
                if (current_mode == 'A') val = (raw / 4095.0f) * 2.0f;
                else                     val = (raw / 4095.0f) * volt_multiplier;

                char msg[40];
                sprintf(msg, "#DATA:M=%c,X=%.2f;\r\n", current_mode, val);
                CDC_Transmit_FS((uint8_t*)msg, strlen(msg));
            }
        }

        /* ── TASK 3: Boost Converter Voltage — 500 ms — PA1 (CH1) ─────── */
        // FIX-01: Was ADC_CHANNEL_0 (PA0). PA1 = ADC_CHANNEL_1.
        // FIX-08: Scaling was *4.0 → max 13.2 V at Vref=3.3 V.
        //         Correct ratio for 5V→12V boost with potential divider:
        //         Vout_max / Vref = 12.0 / 3.3 = 3.636
        if (HAL_GetTick() - tick_500ms >= 500) {
            tick_500ms = HAL_GetTick();
            uint32_t raw    = get_adc_value(ADC_CHANNEL_1);
            float boost_v   = (raw / 4095.0f) * 3.3f * 3.636f;
            char msg[30];
            sprintf(msg, "#BOOST:V=%.2f;\r\n", boost_v);
            CDC_Transmit_FS((uint8_t*)msg, strlen(msg));
        }

        /* ── TASK 4: Temperature — 1000 ms ─────────────────────────────── */
        // FIX-02: Was 2000 ms. Spec requires every 1 second.
        // FIX-12: Was sending raw pulse_count. Now converts to °C:
        //         LM335 → 10 mV/°K → VCO → VCO_HZ_PER_KELVIN Hz/°K
        //         pulse_count (over 1s gate) = frequency in Hz = Kelvin value
        if (HAL_GetTick() - tick_1000ms >= 1000) {
            tick_1000ms = HAL_GetTick();
            float temp_c = get_temperature_celsius();
            char msg[30];
            sprintf(msg, "#TEMP:T=%.1f;\r\n", temp_c);
            CDC_Transmit_FS((uint8_t*)msg, strlen(msg));
        }

        /* ── TASK 5: 7-Segment Multiplexing — 3 ms (non-blocking) ─────── */
        // FIX-15: Was displaying raw pulse_count. Now displays converted °C.
        if (HAL_GetTick() - tick_3ms >= 3) {
            tick_3ms = HAL_GetTick();

            float temp_c = get_temperature_celsius();
            // Display absolute value of temperature, clamped to 3 digits
            int display_val = (int)(temp_c < 0 ? -temp_c : temp_c) % 1000;

            int digits[3] = {
                (display_val / 100) % 10,
                (display_val / 10)  % 10,
                 display_val        % 10
            };
            uint16_t ctrl[] = { GPIO_PIN_5, GPIO_PIN_6, GPIO_PIN_7 };

            // Blank all digit enables, then set segments, then enable one digit
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_RESET);
            uint8_t p = digit_map[digits[current_digit_idx]];
            for (int s = 0; s < 7; s++)
                HAL_GPIO_WritePin(GPIOB, seg_pins[s], (GPIO_PinState)((p >> s) & 0x01));
            HAL_GPIO_WritePin(GPIOB, ctrl[current_digit_idx], GPIO_PIN_SET);

            current_digit_idx = (current_digit_idx + 1) % 3;
        }
    }
    /* USER CODE END WHILE */
}

/* ============================================================================
 * HELPER: Temperature Conversion
 * pulse_count = VCO frequency in Hz over 1s gate = temperature in Kelvin
 * (assuming VCO_HZ_PER_KELVIN = 1.0, adjust for your circuit)
 * ========================================================================== */
float get_temperature_celsius(void)
{
    float kelvin = (float)pulse_count / VCO_HZ_PER_KELVIN;
    return kelvin - KELVIN_OFFSET;
}

/* ============================================================================
 * COMMAND PARSER
 * ========================================================================== */
void parse_command(char* buf)
{
    /* ── Mode Select: GND=PB8:1,PB9:1 | VOLT=1,0 | AMM=0,1 | DSO=0,0 ── */
    if (strncmp(buf, "#MODE:T=", 8) == 0) {
        current_mode = buf[8];
        // FIX-03: Ammeter case corrected to uppercase 'A'
        if      (current_mode == 'G') { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);   HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);   }
        else if (current_mode == 'V') { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);   HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET); }
        else if (current_mode == 'A') { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET); HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);   }
        else if (current_mode == 'D') { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET); HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET);
                                        dso_idx = 0; } // Reset DSO batch on mode entry
        CDC_Transmit_FS((uint8_t*)"#ACK:MODE;\r\n", 12);
    }

    /* ── Voltage Range: 12V=PA6:1,PA7:1 | 16V=1,0 | 24V=0,1 ─────────── */
    else if (strncmp(buf, "#RANGE:V=", 9) == 0) {
        int r = atoi(&buf[9]);
        if      (r == 12) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6, GPIO_PIN_SET);   HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7, GPIO_PIN_SET);   volt_multiplier = 12.0f; }
        else if (r == 16) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6, GPIO_PIN_SET);   HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7, GPIO_PIN_RESET); volt_multiplier = 16.0f; }
        else if (r == 24) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6, GPIO_PIN_RESET); HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7, GPIO_PIN_SET);   volt_multiplier = 24.0f; }
        CDC_Transmit_FS((uint8_t*)"#ACK:RANGE;\r\n", 13);
    }

    /* ── Wave Type: SQ=PA9:1,PA10:1 | TR=1,0 | PA=0,1 | G=0,0 ────────── */
    // FIX-04: Parabolic wave was "pa" (lowercase); corrected to "PA"
    else if (strncmp(buf, "#WAVE:T=", 8) == 0) {
        if      (strstr(buf, "SQ")) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_9, GPIO_PIN_SET);   HAL_GPIO_WritePin(GPIOA, GPIO_PIN_10, GPIO_PIN_SET);   }
        else if (strstr(buf, "TR")) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_9, GPIO_PIN_SET);   HAL_GPIO_WritePin(GPIOA, GPIO_PIN_10, GPIO_PIN_RESET); }
        else if (strstr(buf, "PA")) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_9, GPIO_PIN_RESET); HAL_GPIO_WritePin(GPIOA, GPIO_PIN_10, GPIO_PIN_SET);   }
        else if (strstr(buf, "G"))  { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_9, GPIO_PIN_RESET); HAL_GPIO_WritePin(GPIOA, GPIO_PIN_10, GPIO_PIN_RESET); }
        CDC_Transmit_FS((uint8_t*)"#ACK:WAVE;\r\n", 12);
    }

    /* ── Frequency (TIM2, PA2): 0 Hz stops output, 1–1000 Hz sets freq ── */
    // FIX-13: f=0 was silently ignored. Now explicitly stops output + sends ACK.
    else if (strncmp(buf, "#WAVE:F=", 8) == 0) {
        int f = atoi(&buf[8]);
        if (f == 0) {
            // Stop function generator output
            __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, 0);
            CDC_Transmit_FS((uint8_t*)"#ACK:WAVE;\r\n", 12);
        } else if (f > 0 && f <= 1000) {
            // TIM2 timer clock = 1 MHz (72 MHz / (prescaler+1) = 72 MHz / 72)
            uint32_t arr = (1000000U / (uint32_t)f) - 1U;
            __HAL_TIM_SET_AUTORELOAD(&htim2, arr);
            __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, arr / 2U); // 50% duty
            CDC_Transmit_FS((uint8_t*)"#ACK:WAVE;\r\n", 12);
        }
        // Silently ignore out-of-range values (f > 1000)
    }

    /* ── Voltage Regulator (TIM3, PB0): 0–12 V ─────────────────────────── */
    // FIX-05: strncmp length was 12; "#VREG:V=" is 8 characters.
    // FIX-06: (v/12)*3599 used integer division → always 0 for v<12. Fixed to float.
    else if (strncmp(buf, "#VREG:V=", 8) == 0) {
        int v = atoi(&buf[8]);
        if (v < 0)  v = 0;
        if (v > 12) v = 12;
        uint32_t cmp = (uint32_t)((v / 12.0f) * 3599.0f);
        __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, cmp);
        CDC_Transmit_FS((uint8_t*)"#ACK:VREG;\r\n", 12);
    }

    /* ── Boost Duty Cycle Override (FIX-07: hard 85% cap) ──────────────── */
    else if (strncmp(buf, "#BOOST:D=", 9) == 0) {
        int duty_pct = atoi(&buf[9]);
        if (duty_pct < 0)  duty_pct = 0;
        if (duty_pct > 85) duty_pct = 85;   // Hard cap per problem statement
        uint32_t cmp = (uint32_t)((duty_pct / 100.0f) * BOOST_ARR);
        if (cmp > BOOST_MAX_DUTY) cmp = BOOST_MAX_DUTY;  // Safety double-check
        __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, cmp);
        CDC_Transmit_FS((uint8_t*)"#ACK:BOOST;\r\n", 13);
    }
}

/* ============================================================================
 * ADC READ (single channel, software trigger)
 * FIX-09: Sampling time corrected to 55.5 cycles for signal stability.
 * ========================================================================== */
uint32_t get_adc_value(uint32_t channel)
{
    ADC_ChannelConfTypeDef sConfig = {0};
    sConfig.Channel      = channel;
    sConfig.Rank         = ADC_REGULAR_RANK_1;
    sConfig.SamplingTime = ADC_SAMPLETIME_55CYCLES_5;
    HAL_ADC_ConfigChannel(&hadc1, &sConfig);
    HAL_ADC_Start(&hadc1);
    HAL_ADC_PollForConversion(&hadc1, 10);
    return HAL_ADC_GetValue(&hadc1);
}

/* ============================================================================
 * EXTI CALLBACKS — 555 Timer Temperature Counter
 * PA3 = Gate pulse (enable counting window)
 * PA4 = Reset (clear count, disable counting)
 * PA5 = VCO pulse input (increment counter while gate is active)
 * ========================================================================== */
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
    if      (GPIO_Pin == GPIO_PIN_3) { counting_active = 1; }
    else if (GPIO_Pin == GPIO_PIN_4) { counting_active = 0; pulse_count = 0; }
    else if (GPIO_Pin == GPIO_PIN_5) { if (counting_active) pulse_count++; }
}

/* ============================================================================
 * CLOCK CONFIGURATION
 * HSE 8 MHz → PLL ×9 → SYSCLK 72 MHz
 * APB1 = 36 MHz (but TIM2/3 clock = 72 MHz due to APB1 prescaler × 2 rule)
 * APB2 = 72 MHz
 * USB  = 72 MHz / 1.5 = 48 MHz
 * ADC  = 72 MHz / 6   = 12 MHz
 * ========================================================================== */
void SystemClock_Config(void)
{
    RCC_OscInitTypeDef       RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef       RCC_ClkInitStruct = {0};
    RCC_PeriphCLKInitTypeDef PeriphClkInit     = {0};

    RCC_OscInitStruct.OscillatorType      = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState            = RCC_HSE_ON;
    RCC_OscInitStruct.HSEPredivValue      = RCC_HSE_PREDIV_DIV1;
    RCC_OscInitStruct.HSIState            = RCC_HSI_ON;
    RCC_OscInitStruct.PLL.PLLState        = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource       = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLMUL          = RCC_PLL_MUL9;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) Error_Handler();

    RCC_ClkInitStruct.ClockType      = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                     | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider  = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;   // 36 MHz bus, 72 MHz timer
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;   // 72 MHz
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK) Error_Handler();

    PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_ADC | RCC_PERIPHCLK_USB;
    PeriphClkInit.AdcClockSelection    = RCC_ADCPCLK2_DIV6;      // 12 MHz
    PeriphClkInit.UsbClockSelection    = RCC_USBCLKSOURCE_PLL_DIV1_5; // 48 MHz
    if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit) != HAL_OK) Error_Handler();
}

/* ============================================================================
 * ADC1 INIT
 * FIX-09: Sampling time corrected to 55.5 cycles in the init default channel.
 * ========================================================================== */
static void MX_ADC1_Init(void)
{
    ADC_ChannelConfTypeDef sConfig = {0};

    hadc1.Instance                   = ADC1;
    hadc1.Init.ScanConvMode          = ADC_SCAN_DISABLE;
    hadc1.Init.ContinuousConvMode    = DISABLE;
    hadc1.Init.DiscontinuousConvMode = DISABLE;
    hadc1.Init.ExternalTrigConv      = ADC_SOFTWARE_START;
    hadc1.Init.DataAlign             = ADC_DATAALIGN_RIGHT;
    hadc1.Init.NbrOfConversion       = 1;
    if (HAL_ADC_Init(&hadc1) != HAL_OK) Error_Handler();

    sConfig.Channel      = ADC_CHANNEL_0;           // PA0 — Multimeter input
    sConfig.Rank         = ADC_REGULAR_RANK_1;
    sConfig.SamplingTime = ADC_SAMPLETIME_55CYCLES_5; // FIX-09: was 1CYCLE_5
    if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK) Error_Handler();
}

/* ============================================================================
 * TIM1 INIT — Boost Converter Gate Driver
 * 72 MHz / (PSC+1) / (ARR+1) = 72 MHz / 1 / 360 = 200 kHz
 * ========================================================================== */
static void MX_TIM1_Init(void)
{
    TIM_ClockConfigTypeDef        sClockSourceConfig  = {0};
    TIM_MasterConfigTypeDef       sMasterConfig       = {0};
    TIM_OC_InitTypeDef            sConfigOC           = {0};
    TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

    htim1.Instance               = TIM1;
    htim1.Init.Prescaler         = 0;
    htim1.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim1.Init.Period            = BOOST_ARR;   // 359
    htim1.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim1.Init.RepetitionCounter = 0;
    htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim1) != HAL_OK) Error_Handler();

    sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
    if (HAL_TIM_ConfigClockSource(&htim1, &sClockSourceConfig) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Init(&htim1) != HAL_OK) Error_Handler();

    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode     = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK) Error_Handler();

    sConfigOC.OCMode       = TIM_OCMODE_PWM1;
    sConfigOC.Pulse        = 240;                     // 66.8% initial — safe
    sConfigOC.OCPolarity   = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCNPolarity  = TIM_OCNPOLARITY_HIGH;
    sConfigOC.OCFastMode   = TIM_OCFAST_DISABLE;
    sConfigOC.OCIdleState  = TIM_OCIDLESTATE_RESET;
    sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
    if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1) != HAL_OK) Error_Handler();

    sBreakDeadTimeConfig.OffStateRunMode  = TIM_OSSR_DISABLE;
    sBreakDeadTimeConfig.OffStateIDLEMode = TIM_OSSI_DISABLE;
    sBreakDeadTimeConfig.LockLevel        = TIM_LOCKLEVEL_OFF;
    sBreakDeadTimeConfig.DeadTime         = 0;
    sBreakDeadTimeConfig.BreakState       = TIM_BREAK_DISABLE;
    sBreakDeadTimeConfig.BreakPolarity    = TIM_BREAKPOLARITY_HIGH;
    sBreakDeadTimeConfig.AutomaticOutput  = TIM_AUTOMATICOUTPUT_DISABLE;
    if (HAL_TIMEx_ConfigBreakDeadTime(&htim1, &sBreakDeadTimeConfig) != HAL_OK) Error_Handler();

    HAL_TIM_MspPostInit(&htim1);
}

/* ============================================================================
 * TIM2 INIT — Function Generator Output
 * FIX-16: TIM2 on APB1. APB1 prescaler=2 → timer clock doubled to 72 MHz.
 * Prescaler=71 → tick at 1 MHz. ARR=3570 → 280 Hz initial.
 * ========================================================================== */
static void MX_TIM2_Init(void)
{
    TIM_ClockConfigTypeDef  sClockSourceConfig = {0};
    TIM_MasterConfigTypeDef sMasterConfig      = {0};
    TIM_OC_InitTypeDef      sConfigOC          = {0};

    htim2.Instance               = TIM2;
    htim2.Init.Prescaler         = 71;   // 72 MHz / 72 = 1 MHz timer clock
    htim2.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim2.Init.Period            = 3570;
    htim2.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim2) != HAL_OK) Error_Handler();

    sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
    if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Init(&htim2) != HAL_OK) Error_Handler();

    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode     = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK) Error_Handler();

    sConfigOC.OCMode     = TIM_OCMODE_PWM1;
    sConfigOC.Pulse      = 1785;   // 50% of 3570
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_3) != HAL_OK) Error_Handler();

    HAL_TIM_MspPostInit(&htim2);
}

/* ============================================================================
 * TIM3 INIT — Voltage Regulator PWM
 * 72 MHz / 1 / 3600 = 20 kHz
 * ========================================================================== */
static void MX_TIM3_Init(void)
{
    TIM_ClockConfigTypeDef  sClockSourceConfig = {0};
    TIM_MasterConfigTypeDef sMasterConfig      = {0};
    TIM_OC_InitTypeDef      sConfigOC          = {0};

    htim3.Instance               = TIM3;
    htim3.Init.Prescaler         = 0;
    htim3.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim3.Init.Period            = 3599;
    htim3.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim3) != HAL_OK) Error_Handler();

    sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
    if (HAL_TIM_ConfigClockSource(&htim3, &sClockSourceConfig) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Init(&htim3) != HAL_OK) Error_Handler();

    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode     = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK) Error_Handler();

    sConfigOC.OCMode     = TIM_OCMODE_PWM1;
    sConfigOC.Pulse      = 0;   // 0 V output initially
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_3) != HAL_OK) Error_Handler();

    HAL_TIM_MspPostInit(&htim3);
}

/* ============================================================================
 * GPIO INIT
 * PA0    — ADC CH0 (Multimeter input)        [Analog, handled by ADC]
 * PA1    — ADC CH1 (Boost feedback)          [Analog, handled by ADC]
 * PA3    — EXTI rising (Gate from 555)
 * PA4    — EXTI rising (Reset from 555)
 * PA5    — EXTI rising (VCO count from 555)
 * PA6    — Range select bit 0 (output)
 * PA7    — Range select bit 1 (output)
 * PA9    — Wave type bit 0   (output)
 * PA10   — Wave type bit 1   (output)
 * PB1,PB10-PB15 — 7-seg segments a–g
 * PB5,PB6,PB7   — 7-seg digit enables
 * PB8,PB9       — Mode select bits
 * ========================================================================== */
static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOD_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    // Set all outputs LOW initially
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6 | GPIO_PIN_7 | GPIO_PIN_9 | GPIO_PIN_10, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_1  | GPIO_PIN_5  | GPIO_PIN_6  | GPIO_PIN_7  |
                              GPIO_PIN_8  | GPIO_PIN_9  | GPIO_PIN_10 | GPIO_PIN_11 |
                              GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 | GPIO_PIN_15, GPIO_PIN_RESET);

    // PA3, PA4, PA5 — EXTI rising edge (555 timer signals)
    GPIO_InitStruct.Pin  = GPIO_PIN_3 | GPIO_PIN_4 | GPIO_PIN_5;
    GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    // PA6, PA7 (range select), PA9, PA10 (wave select) — outputs
    GPIO_InitStruct.Pin   = GPIO_PIN_6 | GPIO_PIN_7 | GPIO_PIN_9 | GPIO_PIN_10;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    // PB outputs: 7-seg segments, digit enables, mode select
    GPIO_InitStruct.Pin   = GPIO_PIN_1  | GPIO_PIN_5  | GPIO_PIN_6  | GPIO_PIN_7  |
                            GPIO_PIN_8  | GPIO_PIN_9  | GPIO_PIN_10 | GPIO_PIN_11 |
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 | GPIO_PIN_15;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    // EXTI interrupt priorities
    HAL_NVIC_SetPriority(EXTI3_IRQn,   0, 0); HAL_NVIC_EnableIRQ(EXTI3_IRQn);
    HAL_NVIC_SetPriority(EXTI4_IRQn,   0, 0); HAL_NVIC_EnableIRQ(EXTI4_IRQn);
    HAL_NVIC_SetPriority(EXTI9_5_IRQn, 0, 0); HAL_NVIC_EnableIRQ(EXTI9_5_IRQn);
}

/* ============================================================================
 * ERROR HANDLER
 * ========================================================================== */
void Error_Handler(void)
{
    __disable_irq();
    while (1) {}
}

/* ============================================================================
 * IMPORTANT NOTE — usbd_cdc_if.c change required (FIX-14)
 *
 * In USB_DEVICE/App/usbd_cdc_if.c, find CDC_Receive_FS() and apply:
 *
 *   static int8_t CDC_Receive_FS(uint8_t* Buf, uint32_t *Len)
 *   {
 *       uint32_t len = (*Len > 63) ? 63 : *Len;
 *       memcpy(usb_rx_buffer, Buf, len);
 *       usb_rx_buffer[len] = '\0';   // ← ADD THIS LINE (null termination)
 *       usb_data_ready = 1;
 *       USBD_CDC_SetRxBuffer(&hUsbDeviceFS, &Buf[0]);
 *       USBD_CDC_ReceivePacket(&hUsbDeviceFS);
 *       return (USBD_OK);
 *   }
 * ========================================================================== */
