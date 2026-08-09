import turtle


def draw_petal(t, radius, angle):
    for _ in range(2):
        t.circle(radius, angle)
        t.left(180 - angle)


def draw_rose():
    screen = turtle.Screen()
    screen.title("Turtle 玫瑰花")
    screen.bgcolor("white")

    t = turtle.Turtle()
    t.speed(0)
    t.color("red", "pink")
    t.width(2)

    t.penup()
    t.goto(0, -80)
    t.pendown()

    t.begin_fill()
    for _ in range(6):
        draw_petal(t, 120, 60)
        t.left(60)
    t.end_fill()

    t.color("green")
    t.width(10)
    t.right(90)
    t.penup()
    t.forward(20)
    t.pendown()
    t.forward(180)

    t.width(6)
    t.left(45)
    t.forward(70)
    t.backward(70)
    t.right(90)
    t.forward(70)

    t.hideturtle()
    screen.mainloop()


if __name__ == "__main__":
    draw_rose()
