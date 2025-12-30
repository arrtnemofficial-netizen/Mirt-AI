"""
FSM Contract Tests - Проверка соответствия reducer и core.state_machine.
==========================================================================

Эти тесты гарантируют, что reducer ВСЕГДА использует core.state_machine.get_next_state()
как SSOT, и что нет расхождений между ними.
"""

import pytest

from src.core.state_machine import Intent, State, get_next_state
from src.agents.langgraph.fsm.transition_reducer import compute_transition


class TestFSMContract:
    """Contract tests: reducer должен соответствовать core.state_machine."""

    @pytest.mark.parametrize("current_state", list(State))
    @pytest.mark.parametrize("intent", list(Intent))
    def test_reducer_matches_core_state_machine(
        self,
        current_state: State,
        intent: Intent,
    ):
        """
        КРИТИЧЕСКИЙ ТЕСТ: reducer.next_state должен ВСЕГДА совпадать с core.state_machine.get_next_state().
        
        Это гарантирует, что reducer не создает второй SSOT для переходов.
        """
        # Создаем минимальное состояние
        state = {
            "current_state": current_state.value,
            "selected_products": [],
            "metadata": {},
            "session_id": "test",
        }
        
        # Вызываем reducer
        transition = compute_transition(
            state=state,
            intent=intent.value,
            has_image=False,
            user_message=None,
        )
        
        # Вызываем core SSOT
        expected_next_state = get_next_state(current_state, intent)
        
        # Проверяем соответствие
        assert transition.next_state == expected_next_state.value, (
            f"Contract violation: reducer.next_state ({transition.next_state}) != "
            f"core.get_next_state ({expected_next_state.value}) for "
            f"({current_state.value}, {intent.value})"
        )

    def test_global_priority_intents_always_work(self):
        """Глобальные приоритеты (COMPLAINT, PHOTO_IDENT) должны работать из любого состояния."""
        global_intents = [Intent.COMPLAINT, Intent.PHOTO_IDENT]
        
        for current_state in State:
            for intent in global_intents:
                state = {
                    "current_state": current_state.value,
                    "selected_products": [],
                    "metadata": {},
                    "session_id": "test",
                }
                
                transition = compute_transition(
                    state=state,
                    intent=intent.value,
                    has_image=(intent == Intent.PHOTO_IDENT),
                    user_message=None,
                )
                
                # Проверяем, что переход произошел (не остались в текущем состоянии)
                expected = get_next_state(current_state, intent)
                assert transition.next_state == expected.value, (
                    f"Global priority intent {intent.value} from {current_state.value} "
                    f"should transition to {expected.value}, got {transition.next_state}"
                )

    def test_payment_transition_from_offer(self):
        """STATE_4_OFFER + PAYMENT_DELIVERY → STATE_5_PAYMENT_DELIVERY."""
        state = {
            "current_state": State.STATE_4_OFFER.value,
            "selected_products": [{"name": "Test", "price": 100}],
            "metadata": {},
            "session_id": "test",
        }
        
        transition = compute_transition(
            state=state,
            intent=Intent.PAYMENT_DELIVERY.value,
            has_image=False,
            user_message="Так",
        )
        
        assert transition.next_state == State.STATE_5_PAYMENT_DELIVERY.value
        assert transition.payment_sub_phase == "REQUEST_DATA"
        assert transition.response_policy.snippet_name == "Підтвердження замовлення"
        assert transition.response_policy.use_llm is False

    def test_snippet_idempotency(self):
        """Snippet должен отправляться ровно один раз."""
        state1 = {
            "current_state": State.STATE_4_OFFER.value,
            "selected_products": [{"name": "Test", "price": 100}],
            "metadata": {},
            "session_id": "test",
        }
        
        # Первый раз: snippet должен быть отправлен
        transition1 = compute_transition(
            state=state1,
            intent=Intent.PAYMENT_DELIVERY.value,
            has_image=False,
            user_message="Так",
        )
        assert transition1.response_policy.snippet_name == "Підтвердження замовлення"
        assert transition1.response_policy.use_llm is False
        
        # Второй раз: флаг установлен → snippet НЕ должен быть отправлен
        state2 = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "selected_products": [{"name": "Test", "price": 100}],
            "metadata": {"payment_request_data_sent": True},  # Флаг установлен
            "session_id": "test",
        }
        
        transition2 = compute_transition(
            state=state2,
            intent=Intent.PAYMENT_DELIVERY.value,
            has_image=False,
            user_message="Київ, НП 25",
        )
        
        # Даже если payment_sub_phase = REQUEST_DATA, snippet не должен быть отправлен
        if transition2.payment_sub_phase == "REQUEST_DATA":
            assert transition2.response_policy.snippet_name is None or transition2.response_policy.use_llm is True

    def test_state5_stays_in_state5_without_proof(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: STATE_5 + PAYMENT_DELIVERY должен оставаться в STATE_5
        до получения payment proof (не переходить в STATE_6/STATE_7).
        """
        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "selected_products": [{"name": "Test", "price": 100}],
            "metadata": {},
            "session_id": "test",
        }
        
        transition = compute_transition(
            state=state,
            intent=Intent.PAYMENT_DELIVERY.value,
            has_image=False,
            user_message="Київ, НП 25",
        )
        
        # Должен остаться в STATE_5 (не переходить в STATE_6/STATE_7)
        assert transition.next_state == State.STATE_5_PAYMENT_DELIVERY.value, (
            f"STATE_5 + PAYMENT_DELIVERY should stay in STATE_5 without proof, "
            f"got {transition.next_state}"
        )

    def test_confirmation_priority_over_questions(self):
        """
        Тест: Подтверждение ("Так") должно иметь приоритет над вопросами ("Ціна?").
        Даже если debouncer объединил сообщения, подтверждение должно быть детектировано.
        """
        from src.agents.langgraph.fsm.facts import user_confirmed
        
        state = {
            "current_state": State.STATE_4_OFFER.value,
            "selected_products": [{"name": "Test", "price": 100}],
            "metadata": {},
            "session_id": "test",
        }
        
        # Симулируем "грязный" ввод: "Ціна? Так"
        confirmed = user_confirmed(
            current_state=State.STATE_4_OFFER.value,
            intent="SIZE_HELP",  # Intent может быть неправильным из-за "Ціна?"
            user_message="Ціна? Так",
            metadata={},
        )
        
        # Подтверждение должно быть детектировано
        assert confirmed is True, (
            "Confirmation 'Так' should be detected even if mixed with questions"
        )

    def test_snippet_only_response_no_price_repetition(self):
        """
        Тест: При подтверждении в STATE_4_OFFER должен быть snippet-only ответ
        (без повторения цены через LLM).
        """
        state = {
            "current_state": State.STATE_4_OFFER.value,
            "selected_products": [{"name": "Test", "price": 100}],
            "metadata": {},
            "session_id": "test",
        }
        
        transition = compute_transition(
            state=state,
            intent=Intent.PAYMENT_DELIVERY.value,
            has_image=False,
            user_message="Ціна? Так",  # Смешанный ввод
        )
        
        # Должен быть snippet-only ответ (use_llm=False)
        assert transition.response_policy.snippet_name == "Підтвердження замовлення"
        assert transition.response_policy.use_llm is False, (
            "Snippet-only response should not use LLM (prevents price repetition)"
        )

