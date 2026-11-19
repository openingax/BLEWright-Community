package space.nomoloop.blewright.explorer;

import android.graphics.*;
import android.graphics.drawable.Drawable;

/** Small local vector icon set, drawn on a 24-unit grid with one consistent stroke. */
final class ExplorerIcon extends Drawable {
    private final String kind;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int size;
    ExplorerIcon(String kind, int color, int size) {
        this.kind = kind; this.size = size;
        paint.setColor(color); paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(1.8f);
        paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND);
        setBounds(0, 0, size, size);
    }
    @Override public int getIntrinsicWidth() { return size; }
    @Override public int getIntrinsicHeight() { return size; }
    @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); invalidateSelf(); }
    @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    private void path(Canvas canvas, float... points) {
        Path path = new Path(); path.moveTo(points[0], points[1]);
        for (int i = 2; i < points.length; i += 2) path.lineTo(points[i], points[i+1]);
        canvas.drawPath(path, paint);
    }
    private void circle(Canvas canvas, float x, float y, float radius) { canvas.drawCircle(x, y, radius, paint); }
    private void rect(Canvas canvas, float x, float y, float width, float height) { canvas.drawRoundRect(x, y, x+width, y+height, 2, 2, paint); }
    @Override public void draw(Canvas canvas) {
        canvas.save(); canvas.translate(getBounds().left, getBounds().top);
        canvas.scale(getBounds().width()/24f, getBounds().height()/24f);
        switch (kind) {
            case "bluetooth":
                path(canvas, 7,7, 17,17, 12,21, 12,3, 17,7, 7,17); break;
            case "radar":
                circle(canvas,12,12,9); circle(canvas,12,12,5); path(canvas,12,12,19,5); circle(canvas,12,12,1); break;
            case "filter":
                path(canvas,4,6,20,6); path(canvas,4,12,20,12); path(canvas,4,18,20,18);
                circle(canvas,8,6,2); circle(canvas,16,12,2); circle(canvas,10,18,2); break;
            case "signal":
                path(canvas,4,19,4,17); path(canvas,9,19,9,13); path(canvas,14,19,14,9); path(canvas,19,19,19,5); break;
            case "stop": rect(canvas,5,5,14,14); break;
            case "link":
                path(canvas,9,8,6,8,3,11,3,14,6,17,10,17,13,14);
                path(canvas,15,16,18,16,21,13,21,10,18,7,14,7,11,10); path(canvas,8,14,16,10); break;
            case "unlink":
                path(canvas,9,7,6,7,3,10,3,13,6,16); path(canvas,15,17,18,17,21,14,21,11,18,8);
                path(canvas,4,3,20,21); break;
            case "read": path(canvas,12,3,12,15); path(canvas,7,10,12,15,17,10); path(canvas,4,17,4,21,20,21,20,17); break;
            case "write": path(canvas,4,17,4,21,8,21,20,9,16,5,4,17); path(canvas,13,8,17,12); break;
            case "bell":
                path(canvas,5,17,7,14,7,9,9,5,15,5,17,9,17,14,19,17,5,17);
                path(canvas,10,21,14,21); path(canvas,12,3,12,5); break;
            case "bell-off":
                path(canvas,7,9,7,14,5,17,16,17); path(canvas,11,5,15,5,17,9,17,12);
                path(canvas,10,21,14,21); path(canvas,3,3,21,21); break;
            case "logs":
                rect(canvas,5,3,14,18); path(canvas,9,8,15,8); path(canvas,9,12,15,12); path(canvas,9,16,13,16); break;
            case "copy": rect(canvas,8,8,12,13); path(canvas,15,4,4,4,4,16); break;
            case "trash":
                path(canvas,4,6,20,6); path(canvas,8,6,8,3,16,3,16,6); path(canvas,6,6,7,21,17,21,18,6);
                path(canvas,10,10,10,17); path(canvas,14,10,14,17); break;
            case "refresh":
                canvas.drawArc(4,4,20,20,45,285,false,paint); path(canvas,20,4,20,10,14,10); break;
            case "shield": path(canvas,12,3,20,6,19,14,16,18,12,21,8,18,5,14,4,6,12,3); path(canvas,8,12,11,15,16,9); break;
            case "settings":
                circle(canvas,12,12,4); circle(canvas,12,12,8);
                for(int i=0;i<8;i++){ canvas.save();canvas.rotate(i*45,12,12);path(canvas,12,1,12,4);canvas.restore();} break;
            case "chevron": path(canvas,9,5,16,12,9,19); break;
            case "info": circle(canvas,12,12,9); path(canvas,12,11,12,17); circle(canvas,12,7,0.5f); break;
            case "close": path(canvas,6,6,18,18); path(canvas,18,6,6,18); break;
            case "send": path(canvas,3,4,22,12,3,20,6,12,3,4); path(canvas,6,12,22,12); break;
            case "check": path(canvas,4,12,10,18,20,6); break;
            case "empty":
                path(canvas,3,14,7,5,17,5,21,14,21,20,3,20,3,14,8,14,10,17,14,17,16,14,21,14); break;
            default: rect(canvas,4,4,16,16); path(canvas,8,9,16,9); path(canvas,8,15,16,15);
        }
        canvas.restore();
    }
}
