INTERFACE zif_order_handler PUBLIC.
  METHODS validate
    IMPORTING iv_order_id TYPE zde_order_id
    RETURNING VALUE(rv_ok) TYPE abap_bool.
  METHODS post
    IMPORTING is_order TYPE zorder_hdr.
ENDINTERFACE.
