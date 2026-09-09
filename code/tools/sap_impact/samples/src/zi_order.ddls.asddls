@AbapCatalog.sqlViewName: 'ZIORDER'
@AccessControl.authorizationCheck: #CHECK
@EndUserText.label: '구매오더 인터페이스 뷰'
@OData.publish: true
define root view ZI_ORDER
  as select from zorder_hdr
{
  key order_id as OrderId,
      status   as Status
}
