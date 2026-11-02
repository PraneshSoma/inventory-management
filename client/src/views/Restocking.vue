<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-header">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          class="budget-slider"
          min="0"
          :max="maxBudget"
          step="100"
          :style="{ '--fill': sliderFill }"
          :disabled="maxBudget === 0"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ formatMoney(maxBudget) }}</span>
        </div>
      </div>

      <div v-if="successOrder" class="success-banner">
        <span>{{ t('restocking.orderPlaced', { number: successOrder.order_number, days: successOrder.lead_time_days }) }}</span>
        <router-link to="/orders" class="success-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ candidates.length }})</h3>
        </div>

        <div v-if="candidates.length === 0" class="empty-state">{{ t('restocking.noCandidates') }}</div>
        <template v-else>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th class="col-select">{{ t('restocking.table.select') }}</th>
                  <th>{{ t('restocking.table.sku') }}</th>
                  <th>{{ t('restocking.table.itemName') }}</th>
                  <th>{{ t('restocking.table.category') }}</th>
                  <th>{{ t('restocking.table.trend') }}</th>
                  <th class="num">{{ t('restocking.table.quantity') }}</th>
                  <th class="num">{{ t('restocking.table.unitCost') }}</th>
                  <th class="num">{{ t('restocking.table.lineCost') }}</th>
                  <th>{{ t('restocking.table.leadTime') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in candidates"
                  :key="item.sku"
                  :class="{ 'row-muted': !selectedSkus.includes(item.sku) }"
                >
                  <td class="col-select">
                    <input
                      v-model="selectedSkus"
                      type="checkbox"
                      class="row-checkbox"
                      :value="item.sku"
                      :aria-label="item.sku"
                    />
                  </td>
                  <td><strong>{{ item.sku }}</strong></td>
                  <td>{{ translateProductName(item.name) }}</td>
                  <td>{{ translateCategory(item.category) }}</td>
                  <td>
                    <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                  </td>
                  <td class="num">{{ item.quantity.toLocaleString() }}</td>
                  <td class="num">{{ formatMoneyPrecise(item.unit_cost) }}</td>
                  <td class="num"><strong>{{ formatMoney(item.line_cost) }}</strong></td>
                  <td>{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="summary-bar">
            <div class="summary-stats">
              <div class="summary-stat">
                <div class="summary-label">{{ t('restocking.itemsSelected', { count: selectedItems.length }) }}</div>
              </div>
              <div class="summary-stat">
                <div class="summary-label">{{ t('restocking.selectedTotal') }}</div>
                <div class="summary-value">{{ formatMoney(selectedTotal) }}</div>
              </div>
              <div class="summary-stat">
                <div class="summary-label">{{ t('restocking.remaining') }}</div>
                <div v-if="remaining < 0" class="summary-value over-budget">
                  {{ t('restocking.overBudget') }} ({{ formatMoney(-remaining) }})
                </div>
                <div v-else class="summary-value">{{ formatMoney(remaining) }}</div>
              </div>
              <div class="summary-stat">
                <div class="summary-label">{{ t('restocking.leadTime') }}</div>
                <div class="summary-value">
                  {{ orderLeadTime === null ? '—' : t('restocking.days', { count: orderLeadTime }) }}
                </div>
              </div>
            </div>
            <button class="place-order-btn" :disabled="!canSubmit" @click="placeOrder">
              {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const candidates = ref([])
    const budget = ref(0)
    const selectedSkus = ref([])
    const submitting = ref(false)
    const submitError = ref(null)
    const successOrder = ref(null)

    const maxBudget = computed(() => {
      const total = candidates.value.reduce((sum, c) => sum + c.line_cost, 0)
      return Math.ceil(total / 100) * 100
    })

    // Percentage of the track to paint as filled; consumed by the slider's CSS gradient
    const sliderFill = computed(() => {
      if (maxBudget.value === 0) return '0%'
      return `${(budget.value / maxBudget.value) * 100}%`
    })

    // Candidates arrive ranked by priority. Walk them in order and take each one
    // that still fits in what's left of the budget; an item that doesn't fit is
    // skipped (not a stopping point) so cheaper lower-ranked items can fill the gap.
    const recommendedSkus = computed(() => {
      let left = budget.value
      const skus = []
      for (const c of candidates.value) {
        if (c.line_cost <= left) {
          skus.push(c.sku)
          left -= c.line_cost
        }
      }
      return skus
    })

    const selectedItems = computed(() => {
      return candidates.value.filter(c => selectedSkus.value.includes(c.sku))
    })

    const selectedTotal = computed(() => {
      return selectedItems.value.reduce((sum, c) => sum + c.line_cost, 0)
    })

    const remaining = computed(() => budget.value - selectedTotal.value)

    const orderLeadTime = computed(() => {
      if (selectedItems.value.length === 0) return null
      return Math.max(...selectedItems.value.map(c => c.lead_time_days))
    })

    const canSubmit = computed(() => {
      return selectedItems.value.length > 0 &&
        selectedTotal.value <= budget.value &&
        !submitting.value
    })

    const resetSelection = () => {
      selectedSkus.value = [...recommendedSkus.value]
    }

    watch(budget, resetSelection)

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        candidates.value = await api.getRestockRecommendations()
        budget.value = Math.round(maxBudget.value / 2 / 100) * 100
        // The budget watch won't fire if the value is unchanged, so reset explicitly
        resetSelection()
      } catch (err) {
        error.value = t('restocking.loadError') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (!canSubmit.value) return
      try {
        submitting.value = true
        submitError.value = null
        successOrder.value = null
        successOrder.value = await api.createRestockOrder({
          budget: budget.value,
          items: selectedItems.value.map(c => ({ sku: c.sku, quantity: c.quantity }))
        })
        // Clear the selection so a second click can't submit the same order twice
        selectedSkus.value = []
      } catch (err) {
        const detail = err.response?.data?.detail
        submitError.value = typeof detail === 'string'
          ? `${t('restocking.submitError')}: ${detail}`
          : t('restocking.submitError')
      } finally {
        submitting.value = false
      }
    }

    const formatMoney = (amount) => formatCurrency(amount, currentCurrency.value)
    const formatMoneyPrecise = (amount) => formatCurrencyWithDecimals(amount, currentCurrency.value, 2)

    const translateCategory = (category) => {
      const categoryMap = {
        'Circuit Boards': t('categories.circuitBoards'),
        'Sensors': t('categories.sensors'),
        'Actuators': t('categories.actuators'),
        'Controllers': t('categories.controllers'),
        'Power Supplies': t('categories.powerSupplies')
      }
      return categoryMap[category] || category
    }

    onMounted(loadRecommendations)

    return {
      t,
      loading,
      error,
      candidates,
      budget,
      maxBudget,
      sliderFill,
      selectedSkus,
      selectedItems,
      selectedTotal,
      remaining,
      orderLeadTime,
      canSubmit,
      submitting,
      submitError,
      successOrder,
      placeOrder,
      formatMoney,
      formatMoneyPrecise,
      translateProductName,
      translateCategory
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  margin-bottom: 1rem;
}

.budget-label {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.budget-value {
  font-size: 2.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
  font-variant-numeric: tabular-nums;
}

/* Range input: custom track with a filled portion driven by --fill */
.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(to right, #0f172a 0%, #0f172a var(--fill), #e2e8f0 var(--fill), #e2e8f0 100%);
  outline: none;
  cursor: pointer;
}

.budget-slider:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: white;
  border: 2px solid #0f172a;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.2);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.budget-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: white;
  border: 2px solid #0f172a;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.2);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.budget-slider:hover::-webkit-slider-thumb {
  transform: scale(1.1);
}

.budget-slider:hover::-moz-range-thumb {
  transform: scale(1.1);
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 4px rgba(15, 23, 42, 0.15);
}

.budget-slider:focus-visible::-moz-range-thumb {
  box-shadow: 0 0 0 4px rgba(15, 23, 42, 0.15);
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  color: #64748b;
  font-size: 0.813rem;
}

.success-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
}

.success-link {
  color: #065f46;
  font-weight: 600;
  white-space: nowrap;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748b;
  font-size: 0.938rem;
}

.col-select {
  width: 64px;
  text-align: center;
}

.row-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: #0f172a;
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.row-muted td {
  opacity: 0.45;
}

/* Keep the checkbox fully visible so it reads as actionable */
.row-muted td.col-select {
  opacity: 1;
}

.summary-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1.5rem;
  flex-wrap: wrap;
  margin-top: 1rem;
  padding: 1rem 0 0;
  border-top: 1px solid #e2e8f0;
  background: white;
}

.summary-stats {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  align-items: flex-end;
}

.summary-label {
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.summary-value {
  margin-top: 0.25rem;
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.summary-value.over-budget {
  color: #dc2626;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.75rem 1.5rem;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
