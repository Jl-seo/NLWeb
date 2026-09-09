CLASS zcl_order_service DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    INTERFACES zif_order_handler.
    METHODS read_order
      IMPORTING iv_order_id      TYPE zde_order_id
      RETURNING VALUE(rs_order)  TYPE zorder_hdr.
  PRIVATE SECTION.
    DATA mv_last_id TYPE zde_order_id.
ENDCLASS.

CLASS zcl_order_service IMPLEMENTATION.

  METHOD read_order.
    " 구매오더 헤더 조회
    SELECT SINGLE * FROM zorder_hdr
      INTO @rs_order
      WHERE order_id = @iv_order_id.
    IF sy-subrc <> 0.
      MESSAGE e001(zmm_msg) WITH iv_order_id.
    ENDIF.
    mv_last_id = iv_order_id.
  ENDMETHOD.

  METHOD zif_order_handler~validate.
    DATA(ls_order) = read_order( iv_order_id ).
    rv_ok = COND #( WHEN ls_order-status = 'A' THEN abap_true ELSE abap_false ).
  ENDMETHOD.

  METHOD zif_order_handler~post.
    CALL FUNCTION 'ZFM_ORDER_POST'
      EXPORTING
        is_order = is_order
      EXCEPTIONS
        failed   = 1
        OTHERS   = 2.
  ENDMETHOD.

ENDCLASS.
