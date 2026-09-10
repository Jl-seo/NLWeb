FUNCTION zfm_order_post.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IS_ORDER) TYPE  ZORDER_HDR
*"  EXCEPTIONS
*"     FAILED
*"----------------------------------------------------------------------

  DATA lv_fname TYPE funcname.

  MODIFY zorder_hdr FROM is_order.
  IF sy-subrc <> 0.
    RAISE failed.
  ENDIF.

  " 연계 시스템 통보 (RFC)
  CALL FUNCTION 'ZFM_ORDER_NOTIFY'
    DESTINATION 'ECC_PRD'
    EXPORTING
      iv_order_id = is_order-order_id.

  " 고객별 확장 훅 — 함수명이 커스터마이징 테이블에서 결정됨
  lv_fname = gv_mode.
  CALL FUNCTION lv_fname.

  COMMIT WORK AND WAIT.

ENDFUNCTION.
