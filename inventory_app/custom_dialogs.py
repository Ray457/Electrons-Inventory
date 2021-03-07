import wx
from Inventory_GUI import ViewResultDialog_GUI, CheckoutDialog_GUI
from dbinterface import ItemRecord, DbInterface

import collections


class ViewResultDialog(ViewResultDialog_GUI):
    def __init__(self, *args, **kwargs):
        ViewResultDialog_GUI.__init__(self, *args, **kwargs)  # invoke constructor of the parent class
        self.db = None
        self.item = None
        self.checkout_dialog = CheckoutDialog(parent=self)

    def setup(self, item_to_show: ItemRecord, db: DbInterface):
        self.db = db
        self.item = item_to_show

        # clear the list
        self.list_ctrl_view.DeleteAllItems()

        # note that the first item inserted will end up at the bottom
        view_fields = collections.OrderedDict()
        view_fields["Comment"] = item_to_show.comment
        view_fields["Customer Ref"] = item_to_show.customer_ref
        view_fields["Used by Project"] = item_to_show.used_by_proj
        view_fields["Manufacturer"] = item_to_show.manufacturer
        view_fields["Supplier"] = item_to_show.supplier
        view_fields["Description"] = item_to_show.description
        view_fields["Category"] = item_to_show.category
        view_fields["Quantity"] = item_to_show.quantity
        view_fields["Location"] = item_to_show.location
        view_fields["Manufacturer P/N"] = item_to_show.manufacturer_pn
        view_fields["Supplier P/N"] = item_to_show.supplier_pn
        view_fields["Name"] = item_to_show.name

        for key, value in view_fields.items():
            index = self.list_ctrl_view.InsertItem(index=0, label="")
            self.list_ctrl_view.SetItem(index=index, column=0, label=key)
            self.list_ctrl_view.SetItem(index=index, column=1, label=str(value))
        self.Fit()

    def btn_checkout(self, event):
        self.checkout_dialog.setup(db=self.db, item=self.item)
        self.checkout_dialog.ShowModal()


class CheckoutDialog(CheckoutDialog_GUI):
    def __init__(self, *args, **kwargs):
        CheckoutDialog_GUI.__init__(self, *args, **kwargs)  # invoke constructor of the parent class
        self.db = None
        self.item = None

    def setup(self, db, item: ItemRecord):
        self.db = db  # SQLite database connection to the model
        self.item = item

        # populate the display fields. At least one of these 3 fields should be present
        if item.manufacturer_pn != "":
            name_to_show = item.manufacturer_pn
        elif item.supplier_pn != "":
            name_to_show = item.supplier_pn
        else:
            name_to_show = item.name

        # set the range limit for quantity deduction
        self.spin_ctrl_checkout_quantity.SetRange(0, item.quantity)

        self.label_checkout_item_name.SetLabel(name_to_show)
        self.text_ctrl_proj.SetValue(item.used_by_proj)
        self.label_quantity.SetLabel(str(item.quantity))
        self.Fit()

    def btn_checkout_ok(self, event):
        item: ItemRecord = self.item  # "type cast"
        db: DbInterface = self.db

        item.used_by_proj = self.text_ctrl_proj.GetValue()
        to_deduct: int = self.spin_ctrl_checkout_quantity.GetValue()
        item.quantity -= to_deduct

        db.update_component(item=item)
        self.Show(show=False)

    def btn_checkout_cancel(self, event):
        self.Show(show=False)
