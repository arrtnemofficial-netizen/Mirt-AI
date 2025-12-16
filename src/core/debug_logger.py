from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


logger = logging.getLogger("mirt.debug")


class DebugPhase(str, Enum):
    REQUEST_IN = "📥 REQUEST"
    ROUTING = "🔀 ROUTING"
    LLM_CALL = "🤖 LLM"
    STATE_CHANGE = "📊 STATE"
    RESPONSE_OUT = "📤 RESPONSE"
    ERROR = "❌ ERROR"
    WARNING = "⚠️ WARNING"
    SUCCESS = "✅ SUCCESS"


@dataclass
class RequestContext:
    session_id: str
    start_time: float
    user_message: str
    has_image: bool = False


class DebugLogger:
    _contexts: dict[str, RequestContext] = {}

    TOP_LEFT = "╔"
    TOP_RIGHT = "╗"
    BOTTOM_LEFT = "╚"
    BOTTOM_RIGHT = "╝"
    HORIZONTAL = "═"
    VERTICAL = "║"
    DIVIDER_LEFT = "╠"
    DIVIDER_RIGHT = "╣"

    LINE_WIDTH = 70

    def _box_top(self) -> str:
        return f"{self.TOP_LEFT}{self.HORIZONTAL * self.LINE_WIDTH}{self.TOP_RIGHT}"

    def _box_bottom(self) -> str:
        return f"{self.BOTTOM_LEFT}{self.HORIZONTAL * self.LINE_WIDTH}{self.BOTTOM_RIGHT}"

    def _box_divider(self) -> str:
        return f"{self.DIVIDER_LEFT}{self.HORIZONTAL * self.LINE_WIDTH}{self.DIVIDER_RIGHT}"

    def _box_line(self, content: str) -> str:
        padded = content[:self.LINE_WIDTH - 2].ljust(self.LINE_WIDTH - 2)
        return f"{self.VERTICAL} {padded} {self.VERTICAL}"

    def _truncate(self, text: str, max_len: int = 60) -> str:
        if not text:
            return "(empty)"
        text = text.replace("\n", " ").strip()
        if len(text) > max_len:
            return text[:max_len - 3] + "..."
        return text

    def request_start(
        self,
        session_id: str,
        user_message: str,
        has_image: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._contexts[session_id] = RequestContext(
            session_id=session_id,
            start_time=time.time(),
            user_message=user_message,
            has_image=has_image,
        )
        
        lines = [
            self._box_top(),
            self._box_line(f"{DebugPhase.REQUEST_IN.value} [{session_id}]"),
            self._box_line(f"  msg: \"{self._truncate(user_message)}\""),
            self._box_line(f"  has_image: {has_image}"),
        ]
        
        if metadata:
            channel = metadata.get("channel", "unknown")
            lines.append(self._box_line(f"  channel: {channel}"))
        
        logger.info("\n".join(lines))
    
    def routing_decision(
        self,
        session_id: str,
        current_phase: str,
        detected_intent: str | None,
        destination: str,
        reason: str = "",
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"{DebugPhase.ROUTING.value}"),
            self._box_line(f"  phase: {current_phase} → {destination}"),
            self._box_line(f"  intent: {detected_intent or 'None'}"),
        ]
        
        if reason:
            lines.append(self._box_line(f"  reason: {reason}"))
        
        logger.info("\n".join(lines))
    
    def llm_call(
        self,
        session_id: str,
        node_name: str,
        prompt_preview: str | None = None,
        response_preview: str | None = None,
        model: str = "grok-3-mini",
        tokens_used: int | None = None,
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"{DebugPhase.LLM_CALL.value} [{node_name}]"),
            self._box_line(f"  model: {model}"),
        ]
        
        if prompt_preview:
            lines.append(self._box_line(f"  prompt: \"{self._truncate(prompt_preview)}\""))
        
        if response_preview:
            lines.append(self._box_line(f"  response: \"{self._truncate(response_preview)}\""))
        
        if tokens_used:
            lines.append(self._box_line(f"  tokens: {tokens_used}"))
        
        logger.info("\n".join(lines))
    
    def state_transition(
        self,
        session_id: str,
        old_phase: str,
        new_phase: str,
        old_state: str | None = None,
        new_state: str | None = None,
        reason: str = "",
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"{DebugPhase.STATE_CHANGE.value}"),
            self._box_line(f"  phase: {old_phase} → {new_phase}"),
        ]
        
        if old_state and new_state and old_state != new_state:
            lines.append(self._box_line(f"  state: {old_state} → {new_state}"))
        
        if reason:
            lines.append(self._box_line(f"  reason: {reason}"))
        
        logger.info("\n".join(lines))
    
    def node_entry(
        self,
        session_id: str,
        node_name: str,
        phase: str,
        state_name: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"🔷 NODE [{node_name}]"),
            self._box_line(f"  session: {session_id}"),
            self._box_line(f"  phase: {phase}"),
            self._box_line(f"  state: {state_name}"),
        ]
        
        if extra:
            for key, value in list(extra.items())[:3]:  # Max 3 extra fields
                lines.append(self._box_line(f"  {key}: {self._truncate(str(value), 50)}"))
        
        logger.info("\n".join(lines))
    
    def node_exit(
        self,
        session_id: str,
        node_name: str,
        goto: str,
        new_phase: str,
        response_preview: str | None = None,
    ) -> None:
        lines = [
            self._box_line(f"🔶 NODE [{node_name}] EXIT"),
            self._box_line(f"  goto: {goto}"),
            self._box_line(f"  new_phase: {new_phase}"),
        ]
        
        if response_preview:
            lines.append(self._box_line(f"  response: \"{self._truncate(response_preview)}\""))
        
        logger.info("\n".join(lines))
    
    def warning(
        self,
        session_id: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"{DebugPhase.WARNING.value} [{session_id}]"),
            self._box_line(f"  {self._truncate(message, 60)}"),
        ]
        
        if details:
            for key, value in list(details.items())[:3]:
                lines.append(self._box_line(f"  {key}: {self._truncate(str(value), 50)}"))
        
        logger.warning("\n".join(lines))
    
    def error(
        self,
        session_id: str,
        error_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"{DebugPhase.ERROR.value} [{error_type}]"),
            self._box_line(f"  session: {session_id}"),
            self._box_line(f"  {self._truncate(message, 60)}"),
        ]
        
        if details:
            for key, value in list(details.items())[:3]:
                lines.append(self._box_line(f"  {key}: {self._truncate(str(value), 50)}"))
        
        logger.error("\n".join(lines))
    
    def request_end(
        self,
        session_id: str,
        response_preview: str,
        final_phase: str,
        final_state: str,
    ) -> None:
        ctx = self._contexts.pop(session_id, None)
        duration_ms = int((time.time() - ctx.start_time) * 1000) if ctx else 0
        
        lines = [
            self._box_divider(),
            self._box_line(f"{DebugPhase.RESPONSE_OUT.value} [{duration_ms}ms]"),
            self._box_line(f"  phase: {final_phase}"),
            self._box_line(f"  state: {final_state}"),
            self._box_line(f"  response: \"{self._truncate(response_preview)}\""),
            self._box_bottom(),
        ]
        
        logger.info("\n".join(lines))
    
    def success(
        self,
        session_id: str,
        message: str,
    ) -> None:
        lines = [
            self._box_line(f"{DebugPhase.SUCCESS.value} {self._truncate(message, 55)}"),
        ]
        logger.info("\n".join(lines))
    
    def prompt_debug(
        self,
        session_id: str,
        prompt_name: str,
        prompt_content: str,
        variables: dict[str, Any] | None = None,
    ) -> None:
        lines = [
            self._box_divider(),
            self._box_line(f"📝 PROMPT [{prompt_name}]"),
            self._box_line(f"  preview: \"{self._truncate(prompt_content, 55)}\""),
        ]
        
        if variables:
            lines.append(self._box_line(f"  variables:"))
            for key, value in list(variables.items())[:5]:
                lines.append(self._box_line(f"    {key}: {self._truncate(str(value), 45)}"))
        
        logger.info("\n".join(lines))


debug_log = DebugLogger()
